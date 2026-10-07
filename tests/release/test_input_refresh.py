"""T6c tests use only wheel-derived frozen trees in a new isolated .runtime/t6c-* kit."""
import base64
import csv
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import uuid
import zipfile

import pytest

ROOT=Path(__file__).resolve().parents[2]
OLD=ROOT/'.runtime/t5c-r1-wheel/fashion_scout-0.2.0a1-py3-none-any.whl'
OLD_SHA='9beaa9f5e49063fdb5b36d906b8bac5d1d5a46772f4c5b90a10782a77b772f15'
PS=Path(os.environ['SystemRoot'])/'System32/WindowsPowerShell/v1.0/powershell.exe'


def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()


def source_from(wheel, target):
    target.mkdir()
    with zipfile.ZipFile(wheel) as archive:
        for name in archive.namelist():
            if name.startswith('fashion_scout/'):
                path=target/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(archive.read(name))
    return target


def fixture_wheel(folder, *, marker='fixture-one', version='0.2.0a1', omit=None,
                  distribution='fashion-scout', extra=None, bad_record=False):
    """Ordinary test wheel with genuine RECORD; not a product feature or a release."""
    folder.mkdir()
    old_prefix='fashion_scout-0.2.0a1.dist-info/'
    prefix='fashion_scout-'+version+'.dist-info/'
    with zipfile.ZipFile(OLD) as archive:
        contents={name.replace(old_prefix,prefix,1):archive.read(name) for name in archive.namelist()
                  if name!=omit and not name.endswith('.dist-info/RECORD')}
    contents['fashion_scout/__init__.py']+=('\n# T6C ISOLATED TEST FIXTURE ONLY: '+marker+'\n').encode()
    metadata=contents[prefix+'METADATA'].decode('utf-8').replace('Version: 0.2.0a1','Version: '+version)
    metadata=metadata.replace('Name: fashion-scout','Name: '+distribution)
    contents[prefix+'METADATA']=metadata.encode()
    if extra:contents[extra]=b'# T6C ISOLATED TEST RESOURCE ONLY\n'
    text=io.StringIO(newline='');writer=csv.writer(text,lineterminator='\n')
    for name,data in sorted(contents.items()):
        digest='sha256='+base64.urlsafe_b64encode(hashlib.sha256(data).digest()).decode().rstrip('=')
        writer.writerow((name,digest,str(len(data))))
    writer.writerow((prefix+'RECORD','',''))
    contents[prefix+'RECORD']=text.getvalue().encode()
    if bad_record:contents['fashion_scout/__init__.py']+=b'# changed after RECORD\n'
    wheel=folder/('fashion_scout-'+version+'-py3-none-any.whl')
    with zipfile.ZipFile(wheel,'w',zipfile.ZIP_DEFLATED) as archive:
        for name,data in sorted(contents.items()):archive.writestr(name,data)
    return wheel


@pytest.fixture(scope='module')
def kit():
    work=ROOT/'.runtime'/('t6c-inputs-'+uuid.uuid4().hex[:8]);work.mkdir()
    scripts=work/'scripts/release';shutil.copytree(ROOT/'scripts/release',scripts)
    runtime=work/'.runtime';runtime.mkdir()
    for name in ('requirements-win.lock','runtime-win.json','LICENSE'):shutil.copyfile(ROOT/name,work/name)
    for relative in ('SKILL.md','references/setup.md','references/commands.md','references/browser-acquisition.md'):
        original=ROOT/'skills/fashion-scout'/relative
        target=work/'skills/fashion-scout'/relative
        target.parent.mkdir(parents=True,exist_ok=True)
        shutil.copyfile(original,target)
        assert sha(target)==sha(original)
    shutil.copyfile(ROOT/'.runtime/python.tar.gz',runtime/'python.tar.gz')
    shutil.copytree(ROOT/'.runtime/t6b-dependencies-v1',runtime/'t6b-dependencies-v1')
    legacy=runtime/'t5c-r1-wheel';legacy.mkdir();shutil.copyfile(OLD,legacy/OLD.name)
    source_from(OLD,work/'src')
    logs=work/'logs';logs.mkdir()
    print('T6c isolated kit:',work)
    return work


def build(kit, output, *arguments, expected=0, optimized=False):
    destination=kit/'.runtime'/output
    command=[sys.executable,'-I','-B',*(['-O'] if optimized else []),str(kit/'scripts/release/build_bundle.py'),
             '--output',str(destination),*map(str,arguments)]
    result=subprocess.run(command,cwd=kit,capture_output=True,text=True,encoding='utf-8',timeout=40)
    record={'argv':command,'returncode':result.returncode,'stdout':result.stdout,'stderr':result.stderr}
    log=kit/'logs'/(destination.name+'-'+uuid.uuid4().hex[:6]+'.json')
    log.write_text(json.dumps(record,ensure_ascii=False,indent=2),encoding='utf-8')
    assert result.returncode==expected,record
    return destination,record


def inspect(output, expected_wheel):
    receipt=json.loads((output/'build-receipt.json').read_text('utf-8'))
    manifest=json.loads(Path(receipt['manifest']).read_text('utf-8'))
    assert receipt['app_sha256']==sha(expected_wheel)==manifest['app_sha256']
    assert manifest['app_wheel']=='payload/'+expected_wheel.name
    assert receipt['zip_sha256']==sha(Path(receipt['zip']))
    assert receipt['manifest_sha256']==sha(Path(receipt['manifest']))
    with zipfile.ZipFile(expected_wheel) as wheel:package_files=sum(n.startswith('fashion_scout/') for n in wheel.namelist())
    assert receipt['source_sha256']==manifest['source_sha256'] and receipt['core_files_match_wheel']==package_files
    with zipfile.ZipFile(receipt['zip']) as archive:
        assert archive.read('FashionScout/'+manifest['app_wheel'])==expected_wheel.read_bytes()
        assert not any('/data/' in n or '/.local/' in n or n.endswith(('.key','.sqlite3')) for n in archive.namelist())
        for member in manifest['files']:
            value=archive.read('FashionScout/'+member['path'])
            assert len(value)==member['bytes'] and hashlib.sha256(value).hexdigest()==member['sha256']
        assert len(manifest['dependencies'])==26
        expected_skills={'skills/fashion-scout/'+relative for relative in (
            'SKILL.md','references/setup.md','references/commands.md','references/browser-acquisition.md')}
        assert set(manifest['skill_files'])==expected_skills
        for relative,digest in manifest['skill_files'].items():
            original=ROOT/relative
            assert archive.read('FashionScout/'+relative)==original.read_bytes()
            assert digest==sha(original)
            assert next(m for m in manifest['files'] if m['path']==relative)['sha256']==digest
        for name,row in manifest['source_files'].items():
            with zipfile.ZipFile(expected_wheel) as wheel:value=wheel.read(name)
            assert row=={'bytes':len(value),'sha256':hashlib.sha256(value).hexdigest()}
    return receipt,manifest


def test_default_command_compatibility_and_non_overwrite(kit):
    output,_=build(kit,'t6c-default')
    old=kit/'.runtime/t5c-r1-wheel'/OLD.name
    receipt,manifest=inspect(output,old)
    assert receipt['legacy_defaults'] and receipt['app_sha256']==OLD_SHA
    assert Path(receipt['zip']).name=='FashionScout-0.2.0a1-local-candidate-v1.zip'
    before={p.relative_to(output).as_posix():sha(p) for p in output.rglob('*') if p.is_file()}
    _,rejected=build(kit,'t6c-default',expected=2)
    assert 'never overwritten' in rejected['stderr']
    assert before=={p.relative_to(output).as_posix():sha(p) for p in output.rglob('*') if p.is_file()}
    (kit/'default-evidence.json').write_text(json.dumps(receipt,indent=2),encoding='utf-8')


def test_explicit_byte_identity_versions_and_package_preflight(kit):
    receipts=[]
    for label,marker,version in [('one','one','0.2.0a1'),('two','two','0.2.0a1'),('next','three','0.2.0a2')]:
        app=fixture_wheel(kit/('wheel-'+label),marker=marker,version=version,
                          extra='fashion_scout/browser_ingress_fixture.py' if label=='next' else None)
        source=source_from(app,kit/('source-'+label))
        output,_=build(kit,'t6c-'+label,'--app-wheel',app,'--app-sha256',sha(app),
                       '--source-root',source,'--label','reviewed-input')
        receipt,manifest=inspect(output,app)
        assert sha(app) in receipt['candidate'] and version in receipt['candidate']
        assert receipt['app_version']==manifest['app_version']==version and not receipt['legacy_defaults']
        # Public Status validates dynamic wheel selection, then refuses before preparation.
        extracted=kit/('p-'+label)
        with zipfile.ZipFile(receipt['zip']) as archive:archive.extractall(extracted)
        package=extracted/'FashionScout'
        command=[str(PS),'-NoLogo','-NoProfile','-ExecutionPolicy','Bypass','-File',str(package/'package.ps1'),'-Action','Status']
        result=subprocess.run(command,cwd=package,capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=15)
        (kit/'logs'/('preflight-'+label+'.json')).write_text(json.dumps({'argv':command,'returncode':result.returncode,'stdout':result.stdout,'stderr':result.stderr}),encoding='utf-8')
        assert result.returncode==2 and 'Prepare.cmd first' in result.stdout,result.stdout+result.stderr
        assert not (package/'.local').exists() and not (package/'data').exists()
        receipts.append(receipt)
    assert len({Path(r['zip']).name for r in receipts})==3
    assert len({r['app_sha256'] for r in receipts})==3
    (kit/'explicit-evidence.json').write_text(json.dumps(receipts,indent=2),encoding='utf-8')


@pytest.mark.parametrize('case',['wheel-without-hash','hash-without-wheel','bad-hash','bad-hash-optimized','bad-hash-format',
                                'wheel-empty','hash-empty','both-empty',
                                'unsupported-name','wrong-distribution','missing-resource','missing-migration','record-corrupt',
                                'wheel-traversal','source-byte-change','source-extra-resource','source-missing',
                                'label-traversal','label-empty','label-too-long','output-escape'])
def test_rejected_inputs_have_no_build_artifact(kit,case):
    app=kit/'.runtime/t5c-r1-wheel'/OLD.name;source=kit/'src';digest=OLD_SHA
    extra=[];optimized=case=='bad-hash-optimized'
    if case in {'wrong-distribution','missing-resource','missing-migration','record-corrupt','wheel-traversal'}:
        options={'distribution':'different-package'} if case=='wrong-distribution' else {'omit':'fashion_scout/static/app.css'} if case=='missing-resource' else {'omit':'fashion_scout/db/migrations/009_maintenance.sql'} if case=='missing-migration' else {'bad_record':True} if case=='record-corrupt' else {'extra':'../outside.txt'}
        if case=='missing-migration':
            with zipfile.ZipFile(OLD) as archive:options={'omit':next(n for n in archive.namelist() if n.startswith('fashion_scout/db/migrations/009_'))}
        app=fixture_wheel(kit/('reject-wheel-'+case),**options);digest=sha(app)
        source=source_from(app,kit/('reject-source-'+case))
    if case=='unsupported-name':
        app=kit/'unrelated-0.2.0a1-py3-none-any.whl';shutil.copyfile(OLD,app)
    if case.startswith('source-') and case!='source-missing':
        source=source_from(OLD,kit/('reject-'+case))
        if case=='source-byte-change':(source/'fashion_scout/__init__.py').write_bytes(b'CORE CHANGED AFTER FREEZE')
        else:(source/'fashion_scout/unfrozen_extra.py').write_bytes(b'UNFROZEN RESOURCE')
    if case=='source-missing':source=kit/'no-such-frozen-root'
    arguments=['--app-wheel',app,'--app-sha256',digest,'--source-root',source]
    if case=='wheel-without-hash':arguments=['--app-wheel',app]
    elif case=='hash-without-wheel':arguments=['--app-sha256',digest]
    elif case in {'bad-hash','bad-hash-optimized'}:arguments=['--app-wheel',app,'--app-sha256','0'*64,'--source-root',source]
    elif case=='bad-hash-format':arguments=['--app-wheel',app,'--app-sha256','bad','--source-root',source]
    elif case in {'wheel-empty','hash-empty','both-empty'}:arguments=['--app-wheel','' if case!='hash-empty' else app,'--app-sha256','' if case!='wheel-empty' else digest,'--source-root',source]
    elif case.startswith('label-'):arguments+=['--label','../escape' if case=='label-traversal' else '' if case=='label-empty' else 'x'*33]
    name='t6c-reject-'+case
    if case=='output-escape':name='../t6c-escaped'
    output,record=build(kit,name,*arguments,expected=2,optimized=optimized)
    assert not output.exists(),record


def test_concurrent_builders_cannot_overwrite_same_output(kit):
    output=kit/'.runtime/t6c-race'
    command=[sys.executable,'-I','-B',str(kit/'scripts/release/build_bundle.py'),'--output',str(output)]
    processes=[subprocess.Popen(command,cwd=kit,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,encoding='utf-8') for _ in range(2)]
    records=[]
    for process in processes:
        stdout,stderr=process.communicate(timeout=40)
        records.append({'argv':command,'returncode':process.returncode,'stdout':stdout,'stderr':stderr})
    (kit/'logs/concurrent-build.json').write_text(json.dumps(records,indent=2),encoding='utf-8')
    assert sorted(r['returncode'] for r in records)==[0,2]
    assert all(r['stderr'].startswith('Build refused:') for r in records if r['returncode']==2)
    inspect(output,kit/'.runtime/t5c-r1-wheel'/OLD.name)


def test_package_manifest_cannot_redirect_wheel_or_change_selected_hash(kit):
    app=fixture_wheel(kit/'wheel-binding',marker='binding',version='0.2.0a2')
    source=source_from(app,kit/'source-binding')
    output,_=build(kit,'t6c-binding','--app-wheel',app,'--app-sha256',sha(app),'--source-root',source)
    receipt,_=inspect(output,app)
    with zipfile.ZipFile(receipt['zip']) as archive:archive.extractall(kit/'p-sec')
    package=kit/'p-sec/FashionScout'
    manifest_path=package/'manifest.json';original=manifest_path.read_bytes()
    for value in ('../outside.whl','payload/other-0.2.0a1-py3-none-any.whl','hash-conflict'):
        manifest=json.loads(original)
        if value=='hash-conflict':manifest['app_sha256']='0'*64
        else:manifest['app_wheel']=value
        manifest_path.write_text(json.dumps(manifest),encoding='utf-8')
        try:
            command=[str(PS),'-NoLogo','-NoProfile','-ExecutionPolicy','Bypass','-File',str(package/'package.ps1'),'-Action','Status']
            result=subprocess.run(command,cwd=package,capture_output=True,text=True,encoding='utf-8',timeout=15)
            (kit/'logs'/('manifest-reject-'+uuid.uuid4().hex[:6]+'.json')).write_text(json.dumps({'returncode':result.returncode,'stdout':result.stdout,'stderr':result.stderr}),encoding='utf-8')
            assert result.returncode==2 and ('Unsupported application wheel' in result.stdout or 'hash conflicts' in result.stdout)
            assert not (package/'.local').exists() and not (package/'data').exists()
        finally:manifest_path.write_bytes(original)


def test_local_version_plus_survives_zip_and_public_preflight(kit):
    app=fixture_wheel(kit/'wheel-plus-r1',marker='plus-r1',version='0.2.0a1+browser')
    source=source_from(app,kit/'source-plus-r1')
    output,_=build(kit,'t6c-plus-r1','--app-wheel',app,'--app-sha256',sha(app),'--source-root',source)
    receipt,manifest=inspect(output,app)
    assert manifest['app_version']=='0.2.0a1+browser' and '+browser' in manifest['app_wheel']
    with zipfile.ZipFile(receipt['zip']) as archive:archive.extractall(kit/'p-plus')
    package=kit/'p-plus/FashionScout';assert len(str(package))<=100
    command=[str(PS),'-NoLogo','-NoProfile','-ExecutionPolicy','Bypass','-File',str(package/'package.ps1'),'-Action','Status']
    result=subprocess.run(command,cwd=package,capture_output=True,text=True,encoding='utf-8',timeout=15)
    record={'argv':command,'returncode':result.returncode,'stdout':result.stdout,'stderr':result.stderr}
    (kit/'logs/plus-preflight-r1.json').write_text(json.dumps(record,indent=2),encoding='utf-8')
    assert result.returncode==2 and 'Prepare.cmd first' in result.stdout and not result.stderr,record
    assert not (package/'.local').exists() and not (package/'data').exists()
    (kit/'r1-plus-evidence.json').write_text(json.dumps({'fixture_only':True,'receipt':receipt,'preflight':record,
                                                     'package_root_characters':len(str(package))},indent=2),encoding='utf-8')


def test_plus_manifest_still_rejects_unsafe_members_duplicates_and_bad_hash(kit):
    app=fixture_wheel(kit/'wheel-plus-sec',marker='plus-security-r1',version='0.2.0a1+browser')
    source=source_from(app,kit/'source-plus-sec')
    output,_=build(kit,'t6c-plus-sec','--app-wheel',app,'--app-sha256',sha(app),'--source-root',source)
    receipt,_=inspect(output,app)
    with zipfile.ZipFile(receipt['zip']) as archive:archive.extractall(kit/'p-r1')
    package=kit/'p-r1/FashionScout';assert len(str(package))<=100
    path=package/'manifest.json';original=path.read_bytes()
    for case in ('parent','absolute','metachar','backslash','duplicate','bad-hash'):
        manifest=json.loads(original)
        if case=='duplicate':manifest['files'].append(dict(manifest['files'][0]))
        elif case=='bad-hash':next(e for e in manifest['files'] if e['path']==manifest['app_wheel'])['sha256']='0'*64
        else:manifest['files'][0]['path']={'parent':'../outside+file.txt','absolute':'/outside+file.txt',
                                          'metachar':'payload/a+b;invoke.txt','backslash':'payload/a+b\\file.txt'}[case]
        path.write_text(json.dumps(manifest),encoding='utf-8')
        try:
            command=[str(PS),'-NoLogo','-NoProfile','-ExecutionPolicy','Bypass','-File',str(package/'package.ps1'),'-Action','Status']
            result=subprocess.run(command,cwd=package,capture_output=True,text=True,encoding='utf-8',timeout=15)
            record={'argv':command,'case':case,'returncode':result.returncode,'stdout':result.stdout,'stderr':result.stderr}
            (kit/'logs'/('plus-reject-'+case+'.json')).write_text(json.dumps(record,indent=2),encoding='utf-8')
            assert result.returncode==2 and ('Package hash mismatch' if case=='bad-hash' else 'Invalid manifest member') in result.stdout,record
            assert not (package/'.local').exists() and not (package/'data').exists()
        finally:path.write_bytes(original)
