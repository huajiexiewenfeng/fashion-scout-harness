"""Freeze T6b delivery and check only explicitly owned instances/read-only inputs."""
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
from datetime import datetime, timezone

ROOT=Path(__file__).resolve().parents[2]
DOC=ROOT/'docs/verification'
FINAL=ROOT/'.runtime/t6b-final-v1'
CHECK=ROOT/'.runtime/t6b-checks-57799f5f'


def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()


def main():
    baseline=json.loads((DOC/'T6b-baseline.json').read_text('utf-8'))
    protected={p:sha(ROOT/p) for p in baseline}
    assert protected==baseline,'Protected input changed'
    verification=json.loads((CHECK/'verification.json').read_text('utf-8'))
    receipt=json.loads((FINAL/'build-receipt.json').read_text('utf-8'))
    final_zip=Path(receipt['zip'])
    assert sha(final_zip)==receipt['zip_sha256'] and final_zip.read_bytes()==Path(verification['zip']['zip']).read_bytes()
    assert sha(Path(receipt['manifest']))==receipt['manifest_sha256']
    package=Path(verification['package']);parent=package.parent
    copies={'verification.json':'T6b-verification-v1.json'}
    for name in ('install-original','open-original','open-repeat','stop-original','pip-check','flow-original','port-conflict','repeat-prepare'):
        target={'install-original':'install','open-original':'open','stop-original':'stop'}.get(name,name)
        copies[str((parent/(name+'.json')).relative_to(CHECK))]='T6b-'+target+'-v1.json'
    for source,target in copies.items():
        dest=DOC/target
        assert not dest.exists(), 'Frozen evidence already exists'
        shutil.copyfile(CHECK/source,dest)
    shutil.copyfile(receipt['manifest'],DOC/'T6b-manifest-v1.json')
    stopped=[]
    env={k:v for k,v in os.environ.items() if k.upper() not in {'PYTHONPATH','PYTHONHOME','VIRTUAL_ENV','T6A_AUDIT_DIR'}}
    env.update(PYTHONDONTWRITEBYTECODE='1',PYTHONUTF8='1')
    code='''import json,sys
from fashion_scout.config import Paths
from fashion_scout import launcher
p=Paths.at(sys.argv[1]);d=launcher.read_descriptor(p)
assert d and d['port']!=56117
live={r:bool(launcher.verified_process(p,d,r)) for r in ('web','worker')}
assert not any(live.values())
print(json.dumps({'root':str(p.root),'port':d['port'],'live':live}))
'''
    for folder,label in [('t6b-checks-a7a39863',"真实解压 空格 & 单引号's/FashionScout-0.2.0a1-local-candidate-v1"),
                         ('t6b-checks-fc2f8bbb',"真实解压 空格 & 单引号's/FashionScout"),
                         ('t6b-checks-57799f5f',"真实解压 空格 & 单引号'sx/FashionScout")]:
        work=ROOT/'.runtime'/folder
        package=work/label
        assert work.parent==ROOT/'.runtime' and folder.startswith('t6b-') and package.is_relative_to(work)
        env['T6A_AUDIT_DIR']=str(work/'delivery-audit')
        result=subprocess.run([str(package/'.local/env/Scripts/python.exe'),'-I','-B','-c',code,str(package/'data')],
                              cwd=package,env=env,capture_output=True,text=True,encoding='utf-8',timeout=15)
        assert result.returncode==0 and not result.stderr,result.stderr
        stopped.append(json.loads(result.stdout))
    links=[]
    for doc in [ROOT/'README.md',ROOT/'docs/delivery.zh-CN.md',*DOC.glob('T6b*.md')]:
        for target in re.findall(r'\]\(([^)]+)\)',doc.read_text('utf-8')):
            if target.startswith(('https:','http:','#','app:','codex:')):continue
            resolved=(doc.parent/target.split('#',1)[0]).resolve()
            assert resolved.exists() or resolved==DOC/'T6b-evidence-v1.json',(doc,target)
            links.append({'file':str(doc.relative_to(ROOT)),'target':target})
    files=[ROOT/'README.md',ROOT/'docs/delivery.zh-CN.md',*DOC.glob('T6b*'),
           *(ROOT/'scripts/release').rglob('*'),*(ROOT/'tests/release').rglob('*')]
    hashes={str(p.relative_to(ROOT)):sha(p) for p in files if p.is_file() and '__pycache__' not in p.parts and p.name!='T6b-evidence-v1.json'}
    report={'at':datetime.now(timezone.utc).isoformat(),'scope':'T6b candidate v1; independent review pending',
            'protected_count':len(protected),'protected_sha256':protected,'protected_changed':[],
            'zip':receipt,'validated_zip_bytes_identical':True,'known_owned_instances':stopped,
            'artifact_sha256':hashes,'local_document_links':links,'source_requests':0,'user_preview_accessed':False,
            'global_install':False,'tests':'8 passed in41.85s; T6b-tests-5.txt',
            'remaining':'T2 real assets/T6/new computer/whole Codex/restart/sleep/power failure/human workflow timing unproved'}
    dest=DOC/'T6b-evidence-v1.json';assert not dest.exists()
    dest.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'protected':len(protected),'changed':0,'artifact_hashes':len(hashes),'links':len(links),
                      'zip_sha256':receipt['zip_sha256'],'stopped':stopped},ensure_ascii=False))


if __name__=='__main__':main()
