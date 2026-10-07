"""Freeze R1 evidence without rewriting v1 artifacts or touching Manager fixtures."""
from datetime import datetime,timezone
import hashlib
import json
from pathlib import Path
import zipfile
from fashion_scout import launcher
from fashion_scout.config import Paths

ROOT=Path(__file__).resolve().parents[2]
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()


def main():
    folder=ROOT/'docs/verification';output=folder/'T5c-R1-evidence-v1.json';assert not output.exists()
    v1path=folder/'T5c-evidence-v1.json';v1=json.loads(v1path.read_text('utf-8'))
    allowed={str(Path('src/fashion_scout')/p) for p in ('maintenance/restore.py','maintenance/jobs.py','static/maintenance.js')}
    changed=[n for n,h in v1['sha256'].items() if sha(ROOT/n)!=h]
    assert set(changed)==allowed,changed
    for n,h in v1['protected_sha256'].items():assert sha(ROOT/n)==h,n
    assert sha(Path(v1['wheel']['path']))==v1['wheel']['sha256']
    wheel=next((ROOT/'.runtime/t5c-r1-wheel').glob('*.whl'))
    sources=[p for p in (ROOT/'src/fashion_scout').rglob('*') if p.is_file() and '__pycache__' not in p.parts]
    with zipfile.ZipFile(wheel) as z:
        for p in sources:assert z.read(p.relative_to(ROOT/'src').as_posix())==p.read_bytes()
        assert len([n for n in z.namelist() if n.endswith('.sql')])==9
    old_roots={r['root'] for r in v1['service_audits']};audits=[];process_evidence=[]
    for top in (ROOT/'.runtime').glob('t5c-*'):
        if not top.is_dir() or 'manager' in top.name:continue
        for descriptor in top.rglob('control/runtime.json'):
            root=descriptor.parent.parent
            if str(root) in old_roots:continue
            paths=Paths.at(root);desc=launcher.read_descriptor(paths);assert desc['port']!=56117
            alive=[role for role in ('web','worker') if launcher.verified_process(paths,desc,role)]
            assert not alive,(str(root),alive)
            audits.append({'root':str(root),'alive':alive,'port':desc['port']})
            evidence=root/'evidence.json'
            if evidence.exists():process_evidence.append({'path':str(evidence),'sha256':sha(evidence),'evidence':json.loads(evidence.read_text('utf-8'))})
    browser_path=ROOT/'.runtime/t5c-browser-r1-01/browser-evidence.json'
    browser=json.loads(browser_path.read_text('utf-8'));assert browser['job_count']==1 and browser['source_requests']==0
    observation=json.loads((folder/'T5c-R1-browser-observation.json').read_text('utf-8'))
    assert 'version:' not in observation['mobile']['findings'] and 'fixture' not in observation['mobile']['findings']
    assert observation['mobile']['scroll']<=observation['mobile']['width'] and observation['console_errors']==[]
    files=sources+[p for p in folder.glob('T5c-R1*') if p.is_file()]
    files += [ROOT/'tests/maintenance'/n for n in ('test_restore_r1.py','findings.test.mjs','verify_rework.py')]
    value={'version':'T5c-local-R1','at':datetime.now(timezone.utc).isoformat(),'v1_evidence_sha256':sha(v1path),
        'v1_changed':changed,'v1_unchanged_file_count':len(v1['sha256'])-len(changed),'protected_count':len(v1['protected_sha256']),
        'v1_wheel_unchanged':True,'wheel':{'path':str(wheel),'sha256':sha(wheel),'matching_files':len(sources),'migrations':9},
        'tests':{'targeted':7,'affected_python':85,'frontend':30,'skipped':0},'browser':browser,'browser_observation':observation,
        'service_audits':audits,'process_evidence':process_evidence,'sha256':{str(p.relative_to(ROOT)):sha(p) for p in sorted(set(files))}}
    with output.open('x',encoding='utf-8') as f:json.dump(value,f,ensure_ascii=False,indent=2)
    print(json.dumps({k:value[k] for k in ('version','v1_changed','v1_unchanged_file_count','protected_count','wheel','tests')}))
    print('R1 service roots stopped:',len(audits))


if __name__=='__main__':main()
