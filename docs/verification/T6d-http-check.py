"""Read only the owned smoke HTTP page, then stop the same verified package root."""
import json
import os
from pathlib import Path
import subprocess

ROOT=Path(__file__).resolve().parents[2]
WORK=ROOT/'.runtime/t6c-d-smoke-18206465'
PACKAGE=WORK/'FashionScout'
PS=Path(os.environ['SystemRoot'])/'System32/WindowsPowerShell/v1.0/powershell.exe'
env={k:v for k,v in os.environ.items() if k.upper() not in {'PYTHONPATH','PYTHONHOME','VIRTUAL_ENV'}}
env.update(PYTHONDONTWRITEBYTECODE='1',PYTHONUTF8='1',T6A_AUDIT_DIR=str(WORK/'http-imports'))
records=[]


def run(command,label):
    result=subprocess.run(command,cwd=PACKAGE,env=env,capture_output=True,text=True,encoding='utf-8',timeout=45)
    record={'label':label,'argv':command,'returncode':result.returncode,'stdout':result.stdout,'stderr':result.stderr}
    records.append(record)
    assert result.returncode==0 and not result.stderr,record
    return result


try:
    run([str(PS),'-NoLogo','-NoProfile','-ExecutionPolicy','Bypass','-File',str(PACKAGE/'package.ps1'),'-Action','Open'],'open')
    code='''import json,sys,hashlib
from pathlib import Path
import httpx
from fashion_scout.client import Connection
from fashion_scout.config import Paths
p=Paths.at(sys.argv[1]);cfg=json.loads((p.root/'control/client.json').read_text('utf-8'));c=Connection(p,cfg['port']);c.verify()
base='http://127.0.0.1:'+str(cfg['port'])
with httpx.Client(base_url=base,trust_env=False) as h:
 assert h.get('/v1/products').status_code==401
 g=h.post('/v1/session/bootstrap',json={},headers={'Authorization':'Bearer '+c.token}).json()
 assert h.post('/v1/session/exchange',json={'code':g['bootstrap_url'].split('#')[1]},headers={'Origin':base}).status_code==200
 assert h.get('/').status_code==200
 resources={}
 for f in ('app.js','app.css','bootstrap.js','export-intent.js','exports.js','intent.js','maintenance.js','maintenance-findings.js','maintenance-intent.js'):
  r=h.get('/static/'+f);assert r.status_code==200
  assert r.content==(Path(sys.prefix)/'Lib/site-packages/fashion_scout/static'/f).read_bytes()
  resources[f]=hashlib.sha256(r.content).hexdigest()
print(json.dumps({'authenticated_page':200,'unauthorized':401,'resources':resources}))
'''
    result=run([str(PACKAGE/'.local/env/Scripts/python.exe'),'-I','-B','-c',code,str(PACKAGE/'data')],'page-assets')
    outcome=json.loads(result.stdout)
finally:
    run([str(PS),'-NoLogo','-NoProfile','-ExecutionPolicy','Bypass','-File',str(PACKAGE/'package.ps1'),'-Action','Stop'],'stop')
    code='''import json,sys,sqlite3
from fashion_scout.config import Paths
from fashion_scout import launcher
p=Paths.at(sys.argv[1]);d=launcher.read_descriptor(p);live={r:bool(launcher.verified_process(p,d,r)) for r in ('web','worker')};assert not any(live.values())
c=sqlite3.connect(p.db.as_uri()+'?mode=ro',uri=True)
counts={t:c.execute('SELECT COUNT(*) FROM '+t).fetchone()[0] for t in ('runs','run_requests','collection_http')};assert not any(counts.values());c.close()
print(json.dumps({'live':live,'counts':counts}))
'''
    final=run([str(PACKAGE/'.local/env/Scripts/python.exe'),'-I','-B','-c',code,str(PACKAGE/'data')],'verified-exit')
    (ROOT/'docs/verification/T6d-http-evidence-v1.json').write_text(json.dumps({'records':records,'outcome':outcome,'final':json.loads(final.stdout)},indent=2),encoding='utf-8')
print(json.dumps({'http_smoke_passed':True,'resources':len(outcome['resources']),'final':json.loads(final.stdout)}))
