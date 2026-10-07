import hashlib
import json
from pathlib import Path
import socket
import subprocess
import sys
import time
import uuid
import httpx
import pytest
from fashion_scout import launcher
from fashion_scout.config import Paths
from fashion_scout.db import Database
from fashion_scout.services.runs import Runs
from fashion_scout.processes import owned_process
from fashion_scout.maintenance.jobs import Jobs
from tests.api.helpers import seed

ROOT=Path(__file__).resolve().parents[2]


def port():
    with socket.socket() as s:s.bind(('127.0.0.1',0));return s.getsockname()[1]


def wait(check,seconds=25):
    end=time.monotonic()+seconds
    while time.monotonic()<end:
        result=check()
        if result:return result
        time.sleep(.05)
    raise AssertionError('Maintenance did not reach expected state')


def make(label):
    paths=Paths.at(ROOT/'.runtime'/('t5c-'+label+'-'+uuid.uuid4().hex[:8]));paths.prepare();runs=Runs(Database(paths.db));runs.initialize();seed(runs,paths,count=4)
    with runs.db.write() as c:c.execute('UPDATE product_user_state SET favorite=1')
    return paths,runs,Jobs(paths)


@pytest.mark.process
@pytest.mark.parametrize('mode,stop_kind',[('during_copy','kill'),('during_copy','graceful'),('after_publish','kill')])
def test_real_maintenance_recovery(mode,stop_kind):
    paths,runs,jobs=make('recover');jid,_=jobs.create('backup','recovery',{'destination_id':'local'})
    child=subprocess.Popen([sys.executable,'-m','tests.integration.maintenance_process_helper',str(paths.root),mode],cwd=ROOT,
        stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,creationflags=subprocess.CREATE_NO_WINDOW)
    evidence={'root':str(paths.root),'mode':mode,'stop_kind':stop_kind,'job_id':jid}
    try:
        marker=paths.root/'maintenance-paused.json';wait(marker.exists)
        who=json.loads(marker.read_text('utf-8'))['process'];proc=owned_process(who);assert proc and (proc.pid==child.pid or child.pid in [p.pid for p in proc.parents()])
        with jobs.db.read() as c:before=dict(jobs.row(c,jid))
        def beat():
            with jobs.db.read() as c:return jobs.row(c,jid)['heartbeat_at']>before['heartbeat_at']
        wait(beat,8)
        if stop_kind=='kill':proc.kill();proc.wait(timeout=5)
        else:(paths.root/'maintenance-stop').touch()
        child.wait(timeout=8)
        state=launcher.ensure(paths,port());assert state['resuming_run_ids']==[]
        result=wait(lambda:s if (s:=jobs.get(jid))['state'] in {'partial','succeeded','failed'} else None)
        assert result['state']=='partial' and result['backup_available']
        if mode=='after_publish':assert result['result']['reused']
        with jobs.db.read() as c:
            assert jobs.row(c,jid)['epoch']>before['epoch']
            assert c.execute('SELECT COUNT(*) FROM maintenance_jobs').fetchone()[0]==1
            assert c.execute('SELECT COUNT(*) FROM collection_http').fetchone()[0]==0
        evidence.update(result=result,heartbeat_advanced=True,source_requests=0)
    finally:
        if child.poll() is None:(paths.root/'maintenance-stop').touch();child.wait(timeout=8)
        if launcher.read_descriptor(paths):evidence['stop']=launcher.stop(paths)
        (paths.root/'evidence.json').write_text(json.dumps(evidence,ensure_ascii=False,indent=2),encoding='utf-8')


@pytest.mark.process
def test_real_cli_lost_receipts_and_offline_restore_to_new_service():
    paths,runs,jobs=make('cli');original_port=port();restored_paths=None
    evidence={'root':str(paths.root),'commands':[]}
    def cli(command,body,active=paths,crash=False,expected=0,action='request'):
        f=active.root/(uuid.uuid4().hex+'.json');f.write_text(json.dumps(body),encoding='utf-8')
        argv=[sys.executable,'-m','tests.client.invoke' if crash else 'fashion_scout.client',action]
        if command:argv.append(command)
        argv+=['--data-root',str(active.root),'--json-input',str(f)]
        p=subprocess.run(argv,cwd=ROOT,capture_output=True,text=True,encoding='utf-8',timeout=30)
        assert p.returncode==expected,(p.stdout,p.stderr)
        value=None if crash else json.loads(p.stdout)
        evidence['commands'].append({'command':command or action,'root':str(active.root),'exit':p.returncode,'result':value})
        return value
    try:
        # Parent invocation exits; independent services remain.
        p=subprocess.run([sys.executable,'-m','fashion_scout.launcher','ensure','--data-root',str(paths.root),'--port',str(original_port),'--json'],cwd=ROOT,capture_output=True,timeout=20)
        assert p.returncode==0;cli(None,{'port':original_port},action='configure')
        for command,body in [('verify',{'new_intent':True,'scope':'all'}),('backup',{'new_intent':True,'destination_id':'local'})]:
            cli(command,body,crash=True,expected=73)
            intent=next(i for i in cli('intents',{})['data']['items'] if i['command']==command)
            resumed=cli('resume',{'intent_id':intent['intent_id']})['data']['result'];assert resumed['reused']
            jid=resumed['maintenance']['id'];wait(lambda:jobs.get(jid)['state'] in {'partial','succeeded'})
            cli('maintenance-status',{'maintenance_id':jid})
        backup_id=jid
        setting=cli('storage',{})['data']['storage']
        cli('set-storage',{'expected_revision':setting['revision'],'media_root':str(paths.root/'next-media')},crash=True,expected=73)
        intent=next(i for i in cli('intents',{})['data']['items'] if i['command']=='set-storage')
        assert cli('resume',{'intent_id':intent['intent_id']},expected=4)['error']['code']=='CAS_REVIEW_REQUIRED'
        assert cli('storage',{})['data']['storage']['revision']==setting['revision']+1
        target=ROOT/'.runtime'/('t5c-restored-'+uuid.uuid4().hex[:8])
        restored=subprocess.run([sys.executable,'-m','fashion_scout.maintenance.restore','--data-root',str(paths.root),'--backup-id',backup_id,'--target',str(target),'--allow-partial'],cwd=ROOT,capture_output=True,text=True,encoding='utf-8',timeout=20)
        assert restored.returncode==0,restored.stdout
        recovery=json.loads(restored.stdout);assert not recovery['services_started'] and not (target/'control').exists()
        evidence['restore']=recovery
        original=paths.root/'media';offline=paths.root/'media-offline'
        assert original.resolve().is_relative_to(paths.root) and offline.resolve().is_relative_to(paths.root)
        original.rename(offline)
        restored_paths=Paths.at(target);new_port=port();ready=launcher.ensure(restored_paths,new_port);assert ready['resuming_run_ids']==[]
        cli(None,{'port':new_port},active=restored_paths,action='configure')
        assert cli('favorites',{},active=restored_paths)['data']['total']==4
        from fashion_scout.client import Connection
        connection=Connection(restored_paths,new_port);connection.verify()
        with httpx.Client(trust_env=False) as http:
            response=http.get(f'http://127.0.0.1:{new_port}/v1/assets/fixture-asset-0-0?rendition=original',headers={'Authorization':'Bearer '+connection.token})
        with Database(restored_paths.db).read() as c:expected=c.execute("SELECT sha256 FROM assets WHERE id='fixture-asset-0-0'").fetchone()[0]
        assert response.status_code==200 and hashlib.sha256(response.content).hexdigest()==expected
        exported=cli('export',{'new_intent':True},active=restored_paths)['data']['result']['export']
        from fashion_scout.exports.jobs import Jobs as Exports
        final=wait(lambda:s if (s:=Exports(restored_paths).get(exported['id']))['state']=='partial' else None)
        assert final['download_url']
        with jobs.db.read() as c:
            assert c.execute('SELECT COUNT(*) FROM maintenance_jobs').fetchone()[0]==2
            assert c.execute('SELECT COUNT(*) FROM collection_http').fetchone()[0]==0
        evidence.update(source_requests=0,job_count=2,restored_export=final,asset_hash=expected)
    finally:
        if restored_paths and launcher.read_descriptor(restored_paths):evidence['restored_stop']=launcher.stop(restored_paths)
        if launcher.read_descriptor(paths):evidence['stop']=launcher.stop(paths)
        (paths.root/'evidence.json').write_text(json.dumps(evidence,ensure_ascii=False,indent=2),encoding='utf-8')
