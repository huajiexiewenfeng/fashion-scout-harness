"""Build an offline candidate from a paired wheel/hash and matching frozen source."""
import argparse
import base64
import csv
import email
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import subprocess
import sys
import tarfile
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parents[2]
# Legacy input defaults remain available; explicit inputs never inherit this hash.
APP_SHA = '9beaa9f5e49063fdb5b36d906b8bac5d1d5a46772f4c5b90a10782a77b772f15'
APP = ROOT/'.runtime/t5c-r1-wheel/fashion_scout-0.2.0a1-py3-none-any.whl'
NAME = 'FashionScout-0.2.0a1-local-candidate-v1'
DIRECTORY = 'FashionScout'
VERSION_PATTERN = r'[0-9][A-Za-z0-9._+]{0,31}'
REQUIRED = {'fashion_scout/'+p for p in (
    '__init__.py','config.py','launcher.py','client.py','client_models.py','health.py','worker.py',
    'db/__init__.py','templates/index.html','templates/bootstrap.html','static/app.js','static/app.css','static/exports.js',
    'static/maintenance.js','static/maintenance-findings.js','maintenance/restore.py')}


class BuildError(Exception):
    pass


def require(condition, message):
    if not condition:
        raise BuildError(message)


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def ordinary(path):
    for part in (path,*path.parents):
        if part.exists():
            info=part.lstat()
            require(not stat.S_ISLNK(info.st_mode) and not getattr(info,'st_file_attributes',0)&0x400,
                    'Linked input/output path refused: '+str(part))


def safe_member(name):
    parts=name.split('/')
    require(bool(name) and not PurePosixPath(name).is_absolute() and '\\' not in name
            and all(p and p not in {'.','..'} and not p.endswith(('.', ' '))
                    and not re.match(r'^(CON|PRN|AUX|NUL|COM[0-9]|LPT[0-9])(?:\.|$)',p,re.I)
                    and not any(ord(c)<32 or c in ':<>"|?*' for c in p) for p in parts),
            'Unsafe wheel member: '+name)


def locked():
    rows=[]
    for line in (ROOT/'requirements-win.lock').read_text('utf-8').splitlines():
        if not line.strip() or line.startswith('#'):
            continue
        match=re.fullmatch(r'([\w-]+)==([\w.]+) --hash=sha256:([0-9a-f]{64})',line)
        require(match is not None,'Unsupported lock entry')
        rows.append(match.groups())
    return rows


def frozen_source(source, expected):
    ordinary(source)
    require(source.is_dir(),'Frozen source root is missing')
    package=source/'fashion_scout'
    require(package.is_dir(),'Frozen source must contain fashion_scout/')
    actual={}
    for path in package.rglob('*'):
        if '__pycache__' in path.parts:
            continue
        ordinary(path)
        if path.is_file():
            actual[path.relative_to(source).as_posix()]=path.read_bytes()
    require(set(actual)==set(expected),'Core package resource set changed; use matching frozen source')
    for name,data in expected.items():
        require(actual[name]==data,'Core differs from selected wheel: '+name)
    inventory={name:{'bytes':len(data),'sha256':hashlib.sha256(data).hexdigest()} for name,data in sorted(actual.items())}
    digest=hashlib.sha256(json.dumps(inventory,sort_keys=True,separators=(',',':')).encode()).hexdigest()
    return inventory,digest


def wheel_input(app, digest, source, rows):
    require(re.fullmatch('[0-9a-fA-F]{64}',digest) is not None,'Application SHA256 must be 64 hexadecimal characters')
    digest=digest.lower()
    ordinary(app)
    require(app.is_file(),'Application wheel is missing')
    require(app.stat().st_size<=64*1024**2,'Application wheel exceeds supported input limit')
    require(sha(app)==digest,'Application wheel hash mismatch')
    match=re.fullmatch(r'fashion_scout-('+VERSION_PATTERN+r')-py3-none-any\.whl',app.name)
    require(match is not None,'Unsupported application wheel name/tag; expected fashion_scout-<version>-py3-none-any.whl')
    version=match.group(1)
    prefix='fashion_scout-'+version+'.dist-info/'
    with zipfile.ZipFile(app) as archive:
        infos=archive.infolist();names=[p.filename for p in infos]
        require(len(set(names))==len(names) and len(names)<=1000,'Duplicate or excessive wheel members')
        require(sum(p.file_size for p in infos)<=256*1024**2,'Wheel resources exceed supported input limit')
        for item in infos:
            safe_member(item.filename)
            require(not item.is_dir() and not item.flag_bits&1 and not stat.S_ISLNK(item.external_attr>>16),
                    'Unsupported wheel directory/link/encrypted member')
            require(item.file_size<=16*1024**2,'Wheel member exceeds supported input limit')
            require(item.filename.startswith(('fashion_scout/',prefix)),'Unsupported wheel payload: '+item.filename)
        for name in ('METADATA','WHEEL','RECORD'):
            require(prefix+name in names,'Required wheel metadata missing: '+name)
        metadata=email.message_from_bytes(archive.read(prefix+'METADATA'))
        require(metadata['Name']=='fashion-scout' and metadata['Version']==version,'Wheel distribution/version mismatch')
        require(set(str(metadata['Requires-Python']).replace(' ','').split(','))=={'>=3.13','<3.14'},
                'Unsupported application Python constraint')
        wheel_metadata=email.message_from_bytes(archive.read(prefix+'WHEEL'))
        require(wheel_metadata['Wheel-Version']=='1.0' and wheel_metadata['Root-Is-Purelib']=='true'
                and wheel_metadata.get_all('Tag')==['py3-none-any'],'Unsupported application wheel layout/tag')
        versions={re.sub('[-_.]+','-',name).lower():v for name,v,_ in rows}
        for dependency in metadata.get_all('Requires-Dist',[]):
            spec=dependency.split(';',1)[0].strip()
            dependency_match=re.fullmatch(r'([\w.-]+)==([\w.+]+)',spec)
            require(dependency_match is not None,'Unsupported/unpinned application dependency: '+spec)
            name,requested=dependency_match.groups()
            require(versions.get(re.sub('[-_.]+','-',name).lower())==requested,
                    'Application dependency differs from existing lock: '+spec)
        records={}
        for row in csv.reader(io.StringIO(archive.read(prefix+'RECORD').decode('utf-8'))):
            require(len(row)==3 and row[0] not in records,'Invalid wheel RECORD')
            records[row[0]]=row[1:]
        require(set(records)==set(names),'Wheel RECORD resource set mismatch')
        for name,(record_hash,size) in records.items():
            if name==prefix+'RECORD':
                require(record_hash==size=='','Wheel RECORD self-entry must be empty')
            else:
                data=archive.read(name)
                expected='sha256='+base64.urlsafe_b64encode(hashlib.sha256(data).digest()).decode().rstrip('=')
                require(record_hash==expected and size==str(len(data)),'Wheel RECORD hash mismatch: '+name)
        package={name:archive.read(name) for name in names if name.startswith('fashion_scout/')}
        require(REQUIRED<=set(package),'Required application resource missing: '+', '.join(sorted(REQUIRED-set(package))))
        migrations=sorted(int(PurePosixPath(name).name[:3]) for name in package
                          if re.fullmatch(r'fashion_scout/db/migrations/[0-9]{3}_[^/]+\.sql',name))
        require(len(migrations)>=9 and migrations==list(range(1,len(migrations)+1)),'Required sequential migrations missing')
    inventory,source_digest=frozen_source(source,package)
    return {'version':version,'sha256':digest,'package':package,'source_files':inventory,'source_sha256':source_digest}


def main():
    for stream in (sys.stdout,sys.stderr):
        if hasattr(stream,'reconfigure'):stream.reconfigure(encoding='utf-8')
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',required=True)
    parser.add_argument('--cache',default=str(ROOT/'.runtime/t6b-dependencies-v1'))
    parser.add_argument('--download',action='store_true',help='Only missing hash-pinned runtime/PyPI wheels')
    parser.add_argument('--app-wheel',help='Explicit reviewed wheel; must pair with --app-sha256')
    parser.add_argument('--app-sha256',help='Expected SHA256 for --app-wheel; never inferred')
    parser.add_argument('--source-root',default=str(ROOT/'src'),help='Frozen src root containing fashion_scout/; byte/set check is mandatory')
    parser.add_argument('--label',help='Candidate label: 1-32 lowercase letters/digits/hyphens; explicit candidates include full app SHA')
    args=parser.parse_args()
    if (args.app_wheel is None)!=(args.app_sha256 is None):
        parser.error('--app-wheel and --app-sha256 must be supplied together')
    if args.label is not None and re.fullmatch(r'[a-z0-9][a-z0-9-]{0,31}',args.label) is None:
        parser.error('--label must be 1-32 lowercase letters/digits/hyphens')
    output=Path(args.output).resolve();cache=Path(args.cache).resolve();source=Path(args.source_root).resolve()
    explicit=args.app_wheel is not None
    app=Path(args.app_wheel).resolve() if explicit else APP
    digest=args.app_sha256 if explicit else APP_SHA
    created=False
    try:
        require(output.parent==ROOT/'.runtime' and output.name.startswith(('t6b-','t6c-','t8b-')),
                'Output must be a fresh direct .runtime/t6b-*, t6c-* or t8b-* directory')
        ordinary(output)
        require(not output.exists(),'Fresh output required; prior candidate is never overwritten')
        require(cache.parent==ROOT/'.runtime' and cache.name.startswith(('t6b-','t6c-','t8b-')),'Cache must stay in controlled .runtime')
        rows=locked();selected=wheel_input(app,digest,source,rows)
        candidate=(f"FashionScout-{selected['version']}-{args.label or 'local-candidate'}-app-{selected['sha256']}"
                   if explicit or args.label else NAME)
        require(len(str(output/(candidate+'.zip')))<=250,'Candidate ZIP path too long; choose a shorter controlled output name')
        runtime=ROOT/'.runtime/python.tar.gz'
        pin=json.loads((ROOT/'runtime-win.json').read_text('utf-8'))
        if not runtime.exists():
            require(args.download,'Pinned runtime unavailable; explicit --download required')
            output.mkdir();created=True;runtime=output/'python-download.tar.gz'
            with urllib.request.urlopen(pin['url'],timeout=60) as response,runtime.open('xb') as dest:
                shutil.copyfileobj(response,dest)
        require(sha(runtime)==pin['sha256'],'Runtime hash mismatch')
        ordinary(cache)
        wheels={sha(p):p for p in cache.glob('*.whl')}
        if any(h not in wheels for _,_,h in rows):
            require(args.download,'Incomplete cache; explicit --download required')
            cache.mkdir(exist_ok=True)
            if not created:
                output.mkdir();created=True
            command=[sys.executable,'-I','-m','pip','--isolated','--disable-pip-version-check',
                     'download','--no-deps','--require-hashes','--only-binary=:all:',
                     '--index-url','https://pypi.org/simple','-r',str(ROOT/'requirements-win.lock'),'--dest',str(cache)]
            result=subprocess.run(command,capture_output=True,text=True,encoding='utf-8',timeout=180)
            (output/'dependency-fetch.log').write_text(result.stdout+result.stderr,encoding='utf-8')
            require(result.returncode==0,'Pinned wheel download failed; see dependency-fetch.log')
            wheels={sha(p):p for p in cache.glob('*.whl')}
        require(all(h in wheels for _,_,h in rows),'Missing locked wheel')
        if not created:
            output.mkdir();created=True
        package=output/DIRECTORY;payload=package/'payload';wheelhouse=payload/'wheels'
        wheelhouse.mkdir(parents=True)
        for _,_,h in rows:
            shutil.copyfile(wheels[h],wheelhouse/wheels[h].name)
            require(sha(wheelhouse/wheels[h].name)==h,'Copied dependency hash mismatch')
        shutil.copyfile(app,payload/app.name)
        require(sha(payload/app.name)==selected['sha256'],'Application wheel changed while copying')
        shutil.copyfile(runtime,payload/'python.tar.gz')
        require(sha(payload/'python.tar.gz')==pin['sha256'],'Copied runtime hash mismatch')
        for name in ('runtime-win.json','requirements-win.lock'):
            shutil.copyfile(ROOT/name,payload/name)
        for path in (ROOT/'scripts/release/templates').iterdir():
            if path.is_file():
                target=payload/path.name if path.name=='verify_install.py' else package/path.name
                target.write_text(path.read_text('utf-8-sig'),encoding='utf-8-sig' if path.suffix=='.ps1' else 'utf-8')
        skill_files={}
        skill_root=ROOT/'skills/fashion-scout'
        for relative in ('SKILL.md','references/setup.md','references/commands.md','references/browser-acquisition.md',
                         'references/operations.md','scripts/entry.ps1','agents/openai.yaml'):
            original=skill_root/relative
            ordinary(original)
            require(original.is_file(),'Required conversation Skill material missing: '+relative)
            digest=sha(original)
            target=package/'skills/fashion-scout'/relative
            target.parent.mkdir(parents=True,exist_ok=True)
            shutil.copyfile(original,target)
            require(sha(target)==digest and sha(original)==digest,'Skill material changed while copying: '+relative)
            skill_files['skills/fashion-scout/'+relative]=digest
        (payload/'empty.json').write_text('{}\n',encoding='utf-8')
        (payload/'setup.json').write_text('{"port":8765}\n',encoding='utf-8')
        licenses=package/'licenses';licenses.mkdir()
        shutil.copyfile(ROOT/'LICENSE',licenses/'fashion-scout-MIT.txt')
        notices=[]
        for dependency,version,h in rows:
            path=wheels[h]
            with zipfile.ZipFile(path) as wheel:
                metadata_name=next(n for n in wheel.namelist() if n.endswith('.dist-info/METADATA'))
                metadata=email.message_from_bytes(wheel.read(metadata_name))
                require(metadata['Version']==version and re.sub('[-_.]+','-',metadata['Name']).lower()==re.sub('[-_.]+','-',dependency).lower(),
                        'Dependency wheel identity mismatch')
                license_files=[n for n in wheel.namelist() if n.startswith(metadata_name.rsplit('/',1)[0]+'/')
                               and ('/licenses/' in n or 'license' in n.rsplit('/',1)[-1].lower()
                                    or 'copying' in n.rsplit('/',1)[-1].lower()) and not n.endswith('/')]
                require(bool(license_files),'License absent: '+dependency)
                copied=[]
                for name in license_files:
                    safe_member(name)
                    relative=Path(dependency+'-'+version)/name.split('.dist-info/',1)[1]
                    target=licenses/relative;target.parent.mkdir(parents=True,exist_ok=True)
                    target.write_bytes(wheel.read(name));copied.append(relative.as_posix())
                notices.append({'name':metadata['Name'],'version':version,'wheel':path.name,'sha256':h,
                                'license_expression':metadata['License-Expression'],'license':metadata['License'],'license_files':copied})
        with tarfile.open(runtime,'r:gz') as archive:
            for member in archive.getmembers():
                safe_member(member.name.rstrip('/'))
                require(member.name.startswith('python/') and (member.isdir() or member.isfile()),'Unexpected runtime archive member')
                if member.isfile() and ('license' in Path(member.name).name.lower() or 'copying' in Path(member.name).name.lower()):
                    target=licenses/'runtime'/Path(member.name).relative_to('python')
                    target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(archive.extractfile(member).read())
        (licenses/'dependencies.json').write_text(json.dumps(notices,ensure_ascii=False,indent=2),encoding='utf-8')
        # Catch a frozen input being edited during the build. No current Core work is exempted.
        require(sha(app)==selected['sha256'],'Application input changed during build')
        require(frozen_source(source,selected['package'])[1]==selected['source_sha256'],'Frozen source changed during build')
        for relative,digest in skill_files.items():
            require(sha(package/relative)==digest and sha(ROOT/relative)==digest,'Skill material changed during build: '+relative)
        manifest={'schema':1,'candidate':candidate,'app_wheel':'payload/'+app.name,'app_version':selected['version'],
                  'app_sha256':selected['sha256'],'source_files':selected['source_files'],'source_sha256':selected['source_sha256'],
                  'runtime_sha256':pin['sha256'],'skill_files':skill_files,'data_directory':'data','default_port':8765,'dependencies':notices,
                  'files':[{'path':p.relative_to(package).as_posix(),'bytes':p.stat().st_size,'sha256':sha(p)}
                           for p in sorted(package.rglob('*')) if p.is_file()]}
        manifest_path=package/'manifest.json';manifest_path.write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
        archive_path=output/(candidate+'.zip')
        with zipfile.ZipFile(archive_path,'x',zipfile.ZIP_DEFLATED,compresslevel=6) as archive:
            for path in sorted(package.rglob('*')):
                if path.is_file():
                    info=zipfile.ZipInfo(DIRECTORY+'/'+path.relative_to(package).as_posix(),(2026,10,7,0,0,0))
                    info.compress_type=zipfile.ZIP_DEFLATED;info.external_attr=0o100644<<16
                    archive.writestr(info,path.read_bytes())
        receipt={'zip':str(archive_path),'zip_sha256':sha(archive_path),'bytes':archive_path.stat().st_size,
                 'manifest':str(manifest_path),'manifest_sha256':sha(manifest_path),'candidate':candidate,
                 'files':len(manifest['files']),'dependency_wheels':len(rows),'core_files_match_wheel':len(selected['package']),
                 'app_wheel':str(app),'app_version':selected['version'],'app_sha256':selected['sha256'],
                 'source_root':str(source),'source_sha256':selected['source_sha256'],'runtime_sha256':pin['sha256'],'skill_files':skill_files,
                 'source_network':'No source-site request by builder; fixed dependency download is opt-in',
                 'data_in_zip':False,'services_started':False,'legacy_defaults':not bool(explicit or args.label)}
        (output/'build-receipt.json').write_text(json.dumps(receipt,indent=2),encoding='utf-8')
        print(json.dumps(receipt,ensure_ascii=False),flush=True)
        return 0
    except (BuildError,OSError,ValueError,zipfile.BadZipFile,tarfile.TarError,StopIteration) as exc:
        print('Build refused: '+str(exc),file=sys.stderr)
        return 2


if __name__=='__main__':
    sys.exit(main())
