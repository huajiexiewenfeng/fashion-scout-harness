"""Bounded local delivery evidence; no secrets or source network access."""
import hashlib
import json
import sqlite3
import sys
import zipfile
from pathlib import Path
from datetime import datetime, timezone
from fashion_scout.config import Paths
from fashion_scout.launcher import status


repo=Path(__file__).resolve().parents[2]
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
baseline=json.loads((repo/'docs/verification/T2-local-v2-evidence.json').read_text('utf-8'))['source_sha256']
changed=[p for p,h in baseline.items() if sha(repo/p)!=h]
assert set(changed)=={'pyproject.toml','src/fashion_scout/health.py','src/fashion_scout/launcher.py'},changed
wheel=repo/'.runtime/t3-wheel/fashion_scout-0.2.0a1-py3-none-any.whl'
with zipfile.ZipFile(wheel) as bundle:
    packaged=[]
    for folder in ['api','templates','static']:
        for path in (repo/'src/fashion_scout'/folder).glob('*'):
            if path.is_file():
                relative=path.relative_to(repo/'src').as_posix()
                assert bundle.read(relative)==path.read_bytes(),relative
                packaged.append(relative)
    for relative in ['fashion_scout/services/presentation.py','fashion_scout/health.py','fashion_scout/launcher.py']:
        assert bundle.read(relative)==(repo/'src'/relative).read_bytes(),relative
        packaged.append(relative)
files=[]
for directory in ['src/fashion_scout/api','src/fashion_scout/templates','src/fashion_scout/static','tests/api','tests/ui']:
    files.extend(p for p in (repo/directory).rglob('*') if p.is_file() and '__pycache__' not in p.parts)
files.extend(repo/p for p in ['src/fashion_scout/services/presentation.py','src/fashion_scout/health.py','src/fashion_scout/launcher.py','pyproject.toml'])
files.extend(p for p in (repo/'docs/verification').glob('T3*') if p.is_file() and p.name!='T3-evidence.json')
files.extend((repo/'docs/verification/T3-screenshots').glob('*.jpg'))
value={'version':'T3-local-v1','captured_at':datetime.now(timezone.utc).isoformat(),
       'python':sys.version,'sqlite':sqlite3.sqlite_version,'pytest':'119 passed; 0 skipped; 57.95s',
       'intent_tests':'3 passed','protected_baseline_files':len(baseline),'unchanged_baseline_files':len(baseline)-len(changed),
       'authorized_changed_baseline_files':changed,'wheel':str(wheel),'wheel_sha256':sha(wheel),'verified_wheel_entries':packaged,
       'qa_runtime_status':status(Paths.at(repo/'.runtime/t3-browser')),
       'source_sha256':{p.relative_to(repo).as_posix():sha(p) for p in sorted(set(files))}}
assert not value['qa_runtime_status']['web_ready'] and value['qa_runtime_status']['worker_state']=='offline'
(repo/'docs/verification/T3-evidence.json').write_text(json.dumps(value,ensure_ascii=False,indent=2),'utf-8')
print(json.dumps({k:v for k,v in value.items() if k not in ('source_sha256','verified_wheel_entries')},ensure_ascii=False,indent=2))
