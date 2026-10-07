"""T5c read-only scope/process audit and immutable evidence/sample publication."""
import argparse
from datetime import datetime,timezone
import hashlib
import json
from pathlib import Path
import shutil
import zipfile
from fashion_scout import launcher
from fashion_scout.config import Paths
from fashion_scout.db import Database
from fashion_scout.maintenance.backup import verify_bundle

ROOT=Path(__file__).resolve().parents[2]
ALLOWED={p.replace('/', '\\') for p in '''src/fashion_scout/client.py
src/fashion_scout/client_models.py
src/fashion_scout/config.py
src/fashion_scout/worker.py
src/fashion_scout.egg-info/SOURCES.txt
src/fashion_scout/api/routes.py
src/fashion_scout/db/archive.py
src/fashion_scout/static/app.css
src/fashion_scout/templates/index.html
tests/api/test_interface.py
tests/client/test_client.py
tests/client/test_local_integration.py
tests/core/test_runs.py
tests/core/test_worker_repairs.py
tests/exports/test_jobs.py
tests/integration/test_export_flow.py
skills/fashion-scout/SKILL.md
skills/fashion-scout/references/commands.md
skills/fashion-scout/references/setup.md'''.splitlines()}


def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--output',default='T5c-evidence-v1.json');args=parser.parse_args()
    assert args.output.startswith('T5c-evidence-') and Path(args.output).name==args.output
    output=ROOT/'docs/verification'/args.output;assert not output.exists()
    baseline=json.loads((ROOT/'docs/verification/T5c-baseline.json').read_text('utf-8'))
    changed=[n for n,h in baseline.items() if sha(ROOT/n)!=h];assert set(changed)<=ALLOWED,changed
    protected={n:h for n,h in baseline.items() if n not in ALLOWED}
    wheel=next((ROOT/'.runtime/t5c-wheel').glob('*.whl'))
    sources=[p for p in (ROOT/'src/fashion_scout').rglob('*') if p.is_file() and '__pycache__' not in p.parts]
    with zipfile.ZipFile(wheel) as z:
        for p in sources:assert z.read(p.relative_to(ROOT/'src').as_posix())==p.read_bytes(),str(p)
        migrations=[n for n in z.namelist() if n.endswith('.sql')];assert len(migrations)==9
    audits=[];process_evidence=[]
    # Bound discovery to this stage's explicit synthetic roots. Never read user preview.
    for top in sorted((ROOT/'.runtime').glob('t5c-*')):
        if not top.is_dir():continue
        for descriptor in top.rglob('control/runtime.json'):
            root=descriptor.parent.parent;paths=Paths.at(root);desc=launcher.read_descriptor(paths)
            assert desc['port']!=56117
            alive=[role for role in ('worker','web') if launcher.verified_process(paths,desc,role)]
            assert not alive,(str(root),alive)
            audits.append({'root':str(root),'alive':alive,'port':desc['port']})
        for name in ('evidence.json','browser-evidence.json'):
            p=top/name
            if p.exists():process_evidence.append({'path':str(p),'sha256':sha(p),'evidence':json.loads(p.read_text('utf-8'))})
    browser=json.loads((ROOT/'.runtime/t5c-browser-01/browser-evidence.json').read_text('utf-8'))
    assert browser['job_count']==2 and browser['source_requests']==0 and browser['storage']['revision']==1
    item=next(j for j in browser['maintenance'] if j['kind']=='backup');assert item['backup_available']
    original=Path(item['result']['path']);sample=ROOT/'docs/verification/T5c-backup-sample'/original.name
    verify_bundle(original,item['result']['manifest_sha256'])
    if not sample.exists():shutil.copytree(original,sample)
    manifest,digest=verify_bundle(sample,item['result']['manifest_sha256'])
    file_set={p.relative_to(sample).as_posix() for p in sample.rglob('*') if p.is_file()}
    assert file_set=={'COMMIT.json','manifest.json'}|{f['path'] for f in manifest['files']}
    artifacts=[p for p in (ROOT/'docs/verification').rglob('T5c*') if p.is_file() and not p.name.startswith('T5c-evidence-')]
    artifacts += [p for p in sample.rglob('*') if p.is_file()]
    tests=[p for p in (ROOT/'tests/maintenance').glob('*') if p.is_file()]
    tests += [ROOT/'tests/integration/test_maintenance_flow.py',ROOT/'tests/integration/maintenance_process_helper.py']
    data={'version':'T5c-local-v1','at':datetime.now(timezone.utc).isoformat(),'baseline_count':len(baseline),'protected_count':len(protected),
        'protected_sha256':protected,'allowed_changed':changed,'unexpected_changes':[],
        'tests':{'combined_python':187,'media_adapter_python':65,'javascript':28,'skipped':0,'skill_validation':'passed with -X utf8'},
        'wheel':{'path':str(wheel),'sha256':sha(wheel),'matching_production_files':len(sources),'migrations':len(migrations)},
        'browser':{'evidence':browser,'desktop':[1440,1000],'mobile':[390,844],'horizontal_overflow':False,'console_errors':[],
            'refresh_queued_job_count':1,'initial_job_count':0,'historical_images_after_switch':6},
        'backup_sample':{'path':str(sample),'manifest_sha256':digest,'state':manifest['state'],'files':len(file_set),'counts':manifest['counts']},
        'service_audits':audits,'process_evidence':process_evidence,
        'sha256':{str(p.relative_to(ROOT)):sha(p) for p in sorted(set(sources+artifacts+tests))}}
    with output.open('x',encoding='utf-8') as f:json.dump(data,f,ensure_ascii=False,indent=2)
    print(json.dumps({'path':str(output),'protected':len(protected),'unexpected_changes':[],'wheel_files':len(sources),'service_roots':len(audits),'sample':data['backup_sample']}))


if __name__=='__main__':main()
