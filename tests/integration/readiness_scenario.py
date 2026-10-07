"""Runs only under the unpacked wheel environment, reusing existing synthetic seed."""
import hashlib
import json
import os
from pathlib import Path
import runpy
import socket
import subprocess
import sys
import time
import uuid
import httpx
from fashion_scout import launcher
from fashion_scout.config import Paths
from fashion_scout.db import Database
from fashion_scout.services.runs import Runs
from fashion_scout.client import Connection
from fashion_scout.exports.jobs import Jobs as Exports
from fashion_scout.maintenance.jobs import Jobs as Maintenance
from fashion_scout.maintenance.backup import verify_bundle
from fashion_scout.client_models import MODELS

ROOT=Path(sys.argv[1]);WORK=Path(sys.argv[2]);paths=Paths.at(WORK/'data');restored=Paths.at(WORK/'restored')
assert WORK.parent==ROOT/'.runtime' and WORK.name.startswith('t6a-')
assert Path(launcher.__file__).is_relative_to(Path(sys.prefix)/'Lib/site-packages/fashion_scout')
evidence={'synthetic_only':True,'commands':[],'models':sorted(MODELS)}
def port():
    with socket.socket() as s:s.bind(('127.0.0.1',0));value=s.getsockname()[1]
    assert value!=56117;return value
def invoke(module,args):
    cmd=[sys.executable,'-B','-m',module,*args]
    result=subprocess.run(cmd,cwd=WORK,capture_output=True,text=True,encoding='utf-8',timeout=35)
    record={'argv':cmd,'returncode':result.returncode,'stdout':result.stdout,'stderr':result.stderr}
    evidence['commands'].append(record);print(json.dumps(record,ensure_ascii=True),flush=True)
    assert result.returncode==0,record
    return json.loads(result.stdout) if '--help' not in args else result.stdout
def cli(command,payload,active=paths,action='request'):
    f=WORK/(uuid.uuid4().hex+'.json');f.write_text(json.dumps(payload),encoding='utf-8')
    return invoke('fashion_scout.client',[action,*([command] if command else []),'--data-root',str(active.root),'--json-input',str(f)])
def wait(fn):
    end=time.monotonic()+20
    while time.monotonic()<end:
        value=fn()
        if value:return value
        time.sleep(.05)
    raise AssertionError('Local job did not finish')
def terminal(store,jid):
    value=store.get(jid);return value if value['state'] in {'succeeded','partial','failed'} else None
try:
    for module in ('fashion_scout.launcher','fashion_scout.client','fashion_scout.health','fashion_scout.worker','fashion_scout.maintenance.restore'):
        invoke(module,['--help'])
    number=port();cli(None,{'port':number},action='configure');cli('ensure',{})
    for command in ('status','new','favorites','latest','maintenance','storage','sites','default-plan'):cli(command,{})
    cli('open',{})
    connection=Connection(paths,number);connection.verify()
    with httpx.Client(base_url=f'http://127.0.0.1:{number}',trust_env=False) as http:
        assert http.get('/v1/products').status_code==401
        auth={'Authorization':'Bearer '+connection.token};origin={'Origin':f'http://127.0.0.1:{number}'}
        grant=http.post('/v1/session/bootstrap',json={},headers=auth).json()
        code=grant['bootstrap_url'].split('#')[1]
        assert http.post('/v1/session/exchange',json={'code':code},headers=origin).status_code==200
        response=http.get('/');assert response.status_code==200 and 'maintenance-panel' in response.text
        resources={}
        for name in ('app.js','maintenance.js','maintenance-findings.js','exports.js','app.css'):
            r=http.get('/static/'+name);assert r.status_code==200
            file=Path(sys.prefix)/'Lib/site-packages/fashion_scout/static'/name
            assert r.content==file.read_bytes();resources[name]=hashlib.sha256(r.content).hexdigest()
        assert http.post('/v1/maintenance/verify',json={'request_key':'csrf-guard','scope':'all'},headers=origin).status_code==403
        evidence['page']={'http':200,'resources':resources,'unauthorized_read':401,'missing_csrf_write':403,'rendering':'HTTP document/assets verified; browser rendering reuses accepted T3/T5 evidence'}
    db=Database(paths.db)
    with db.read() as c:
        assert c.execute('SELECT COUNT(*) FROM runs').fetchone()[0]==0
        assert c.execute('SELECT COUNT(*) FROM maintenance_jobs').fetchone()[0]==0
        evidence['empty_entry']={'runs':0,'source_requests':c.execute('SELECT COUNT(*) FROM collection_http').fetchone()[0],
            'schema':[r[0] for r in c.execute('SELECT version FROM schema_migrations ORDER BY version')]}
    seed=runpy.run_path(str(ROOT/'tests/api/helpers.py'))['seed'];seed(Runs(db),paths,count=4)
    assert cli('new',{})['data']['total']==3
    product=cli('product',{'product_id':'fixture-000'})['data']['product']
    cli('user-state',{'product_id':'fixture-000','expected_revision':product['user_state']['revision'],'favorite':True})
    assert cli('favorites',{})['data']['total']==1
    export=cli('export',{'new_intent':True})['data']['result']['export'];finished=wait(lambda:terminal(Exports(paths),export['id']))
    assert finished['state']=='succeeded' and finished['download_url']
    with httpx.Client(trust_env=False) as http:
        response=http.get(f'http://127.0.0.1:{number}'+finished['download_url'],headers=auth)
    assert response.status_code==200 and hashlib.sha256(response.content).hexdigest()==finished['sha256']
    (WORK/'favorites.zip').write_bytes(response.content);evidence['export']=finished
    for command,body in [('verify',{'new_intent':True,'scope':'all'}),('backup',{'new_intent':True,'destination_id':'local'})]:
        job=cli(command,body)['data']['result']['maintenance'];value=wait(lambda:terminal(Maintenance(paths),job['id']))
        assert value['state']=='partial';cli('maintenance-status',{'maintenance_id':job['id']});evidence[command]=value
    backup=evidence['backup'];assert backup['backup_available'];verify_bundle(Path(backup['result']['path']),backup['result']['manifest_sha256'])
    f=WORK/'restore-input.json';f.write_text(json.dumps({'backup_id':backup['id'],'target':str(restored.root),'allow_partial':True}),encoding='utf-8')
    result=invoke('fashion_scout.maintenance.restore',['--data-root',str(paths.root),'--json-input',str(f)])
    assert result['state']=='partial' and not result['services_started'] and not (restored.root/'control').exists();evidence['restore']=result
    with Database(restored.db).read() as c:
        assert c.execute('SELECT COUNT(*) FROM product_user_state WHERE favorite=1').fetchone()[0]==1
        for relative,digest,path in c.execute('SELECT a.relative_path,a.sha256,r.path FROM assets a JOIN storage_roots r ON r.id=a.root_id'):
            assert hashlib.sha256((Path(path)/relative).read_bytes()).hexdigest()==digest
    with db.read() as c:
        evidence['final_counts']={'runs':c.execute('SELECT COUNT(*) FROM runs').fetchone()[0],
            'synthetic_terminal_runs':c.execute("SELECT COUNT(*) FROM runs WHERE id='synthetic-fixture-run' AND state='succeeded'").fetchone()[0],
            'source_requests':c.execute('SELECT COUNT(*) FROM collection_http').fetchone()[0],
            'run_intents':c.execute('SELECT COUNT(*) FROM run_requests').fetchone()[0]}
        assert evidence['final_counts']=={'runs':1,'synthetic_terminal_runs':1,'source_requests':0,'run_intents':0}
finally:
    if launcher.read_descriptor(paths):
        evidence['stop']=invoke('fashion_scout.launcher',['stop','--data-root',str(paths.root),'--graceful','--json'])
        desc=launcher.read_descriptor(paths)
        assert not any(launcher.verified_process(paths,desc,r) for r in ('web','worker'))
    (WORK/'scenario.json').write_text(json.dumps(evidence,ensure_ascii=False,indent=2),encoding='utf-8')
