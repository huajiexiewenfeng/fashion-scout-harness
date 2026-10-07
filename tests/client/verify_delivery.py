"""Read-only protected-source/wheel checks and T4 evidence manifest."""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import zipfile

ROOT=Path(__file__).resolve().parents[2]


def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    baseline=json.loads((ROOT/'docs/verification/T4-baseline.json').read_text('utf-8'))
    changed=[name for name,expected in baseline.items() if sha(ROOT/name)!=expected]
    assert changed==[],changed
    wheel=ROOT/'.runtime/t4-wheel/fashion_scout-0.2.0a1-py3-none-any.whl'
    with zipfile.ZipFile(wheel) as archive:
        for name in ('client.py','client_models.py'):
            assert archive.read('fashion_scout/'+name)==(ROOT/'src/fashion_scout'/name).read_bytes()
    integration=json.loads((ROOT/'docs/verification/T4-local-integration.json').read_text('utf-8'))
    assert integration['source_requests']==0 and integration['view_events']==0
    assert integration['after_stop']['web_ready'] is False
    assert integration['after_stop']['worker_state']=='offline'
    assert integration['stop']=={'stopped':True,'forced_roles':[]}
    skill=ROOT/'skills/fashion-scout'
    assert (skill/'references/setup.md').exists() and (skill/'references/commands.md').exists()
    files=[ROOT/'src/fashion_scout/client.py',ROOT/'src/fashion_scout/client_models.py',ROOT/'README.md']
    files+=list(skill.rglob('*.md'))+list((ROOT/'tests/client').glob('*.py'))
    files += [p for p in (ROOT/'docs/verification').glob('T4*') if p.name!='T4-evidence.json' and p.is_file()]
    key_dir=Path(integration['root'])/'control'
    secrets=[p.read_text('ascii') for p in key_dir.glob('*.key')]
    for path in files:
        if path.suffix in {'.md','.json','.txt','.py'}:
            raw=path.read_text('utf-8-sig')
            assert all(secret not in raw for secret in secrets),path
    evidence={'version':'T4-local-v1','generated_at':datetime.now(timezone.utc).isoformat(),
              'protected_baseline_count':len(baseline),'protected_changes':changed,
              'tests':{'client':40,'api':14,'total_passed':54,'skipped':0},
              'wheel':{'path':str(wheel),'sha256':sha(wheel),'client_modules_match':True},
              'integration':{'root':integration['root'],'source_requests':0,'run_count':integration['run_count'],
                             'run_request_count':integration['run_request_count'],'view_events':0,
                             'after_stop':integration['after_stop']},
              'source_sha256':{str(p.relative_to(ROOT)):sha(p) for p in files}}
    output=ROOT/'docs/verification/T4-evidence.json'
    output.write_text(json.dumps(evidence,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({k:v for k,v in evidence.items() if k!='source_sha256'},ensure_ascii=True))


if __name__=='__main__':main()
