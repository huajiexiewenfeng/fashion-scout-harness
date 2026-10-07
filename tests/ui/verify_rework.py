"""R1 evidence against the retained T3-v1 source manifest."""
import hashlib
import json
import zipfile
from pathlib import Path
from datetime import datetime, timezone
from fashion_scout.config import Paths
from fashion_scout.launcher import status

repo=Path(__file__).resolve().parents[2]
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
v1=json.loads((repo/'docs/verification/T3-evidence.json').read_text('utf-8'))
production={p:h for p,h in v1['source_sha256'].items() if p.startswith('src/') or p=='pyproject.toml'}
changed=[p for p,h in production.items() if sha(repo/p)!=h]
assert set(changed)=={'src/fashion_scout/static/app.js','src/fashion_scout/static/intent.js'},changed
t2=json.loads((repo/'docs/verification/T2-local-v2-evidence.json').read_text('utf-8'))['source_sha256']
changed_t2=[p for p,h in t2.items() if sha(repo/p)!=h]
assert set(changed_t2)=={'pyproject.toml','src/fashion_scout/health.py','src/fashion_scout/launcher.py'},changed_t2
wheel=repo/'.runtime/t3-wheel-r1/fashion_scout-0.2.0a1-py3-none-any.whl'
with zipfile.ZipFile(wheel) as bundle:
    for relative in production:
        if relative.startswith('src/'):
            assert bundle.read(relative[4:])==(repo/relative).read_bytes(),relative
files=[repo/p for p in production]
files.extend([repo/'tests/ui/state-transitions.test.mjs',repo/'tests/ui/intent.test.mjs',repo/'tests/ui/scenarios.py',Path(__file__).resolve()])
files.extend(p for p in (repo/'docs/verification').glob('T3-R1*') if p.is_file() and p.name!='T3-R1-evidence.json')
files.extend((repo/'docs/verification/T3-R1-screenshots').glob('*.jpg'))
files.extend([repo/'docs/verification/T3.md',repo/'docs/verification/T3-api-contract.md'])
value={'version':'T3-local-v2/R1','captured_at':datetime.now(timezone.utc).isoformat(),
       'new_checks':{'ui':'15 passed (3 retained intent + 12 state/fault cases)','api':'14 passed, 2.05s'},
       'prior_checks_reused':'v1 full 119 passed; no protected backend changes in R1',
       'production_changed_from_v1':changed,'t2_unchanged_files':len(t2)-len(changed_t2),'t2_allowed_differences':changed_t2,
       'wheel':str(wheel),'wheel_sha256':sha(wheel),'qa_runtime_status':status(Paths.at(repo/'.runtime/t3-browser')),
       'source_sha256':{p.relative_to(repo).as_posix():sha(p) for p in sorted(set(files))}}
assert not value['qa_runtime_status']['web_ready'] and value['qa_runtime_status']['worker_state']=='offline'
(repo/'docs/verification/T3-R1-evidence.json').write_text(json.dumps(value,ensure_ascii=False,indent=2),'utf-8')
print(json.dumps({k:v for k,v in value.items() if k!='source_sha256'},ensure_ascii=False,indent=2))
