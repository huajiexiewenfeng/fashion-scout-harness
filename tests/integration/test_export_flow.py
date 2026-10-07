import json
from pathlib import Path
import socket
import subprocess
import sys
import time
import uuid
import pytest
from fashion_scout.config import Paths
from fashion_scout.db import Database
from fashion_scout.services.runs import Runs
from fashion_scout.exports.jobs import Jobs
from fashion_scout import launcher
from fashion_scout.processes import owned_process
from tests.api.helpers import seed

ROOT=Path(__file__).resolve().parents[2]


def wait(predicate,seconds=25):
    end=time.monotonic()+seconds
    while time.monotonic()<end:
        result=predicate()
        if result:return result
        time.sleep(.05)
    raise AssertionError('Export did not reach expected local state')


def make_root(label,count=4):
    root=ROOT/'.runtime'/('t5c-export-'+label+'-'+uuid.uuid4().hex[:10]);paths=Paths.at(root);paths.prepare()
    runs=Runs(Database(paths.db));runs.initialize();seed(runs,paths,count=count)
    with runs.db.write() as conn:conn.execute('UPDATE product_user_state SET favorite=1')
    with socket.socket() as sock:sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
    return paths,runs,Jobs(paths),port


@pytest.mark.process
@pytest.mark.parametrize('mode,stop_kind',[('during_copy','kill'),('during_copy','graceful'),('after_publish','kill')])
def test_real_worker_recovery_same_task_and_attempt(mode,stop_kind):
    paths,runs,jobs,port=make_root('recovery');jid,_=jobs.create('recover')
    helper=subprocess.Popen([sys.executable,'-m','tests.integration.export_process_helper',str(paths.root),mode],cwd=ROOT,
        stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,creationflags=subprocess.CREATE_NO_WINDOW)
    evidence={'mode':mode,'stop_kind':stop_kind,'root':str(paths.root),'export_id':jid}
    try:
        marker=paths.root/'export-paused.json';wait(marker.exists)
        who=json.loads(marker.read_text('utf-8'))['process'];proc=owned_process(who);assert proc
        assert helper.pid==proc.pid or helper.pid in [p.pid for p in proc.parents()]
        with jobs.db.read() as conn:old=dict(jobs.row(conn,jid))
        assert old['state']=='running'
        if stop_kind=='kill':proc.kill();proc.wait(timeout=5)
        else:(paths.root/'export-stop').touch()
        helper.wait(timeout=10)
        result=launcher.ensure(paths,port);assert result['resuming_run_ids']==[]
        done=wait(lambda: (s if (s:=jobs.get(jid))['state'] in {'partial','succeeded'} else None))
        with jobs.db.read() as conn:
            row=dict(jobs.row(conn,jid));saved=json.loads(row['result_json'])
            assert row['epoch']>old['epoch'] and row['attempt']==1
            assert conn.execute('SELECT COUNT(*) FROM export_jobs').fetchone()[0]==1
            assert conn.execute('SELECT COUNT(*) FROM collection_http').fetchone()[0]==0
        if mode=='after_publish':assert saved['reused']
        stream,size=jobs.download(jid);assert stream.read(2)==b'PK';stream.close()
        evidence.update(final=done,reused_after_publish=saved['reused'],source_requests=0)
    finally:
        if helper.poll() is None:
            (paths.root/'export-stop').touch();helper.wait(timeout=10)
        if launcher.read_descriptor(paths):evidence['stop']=launcher.stop(paths)
        (paths.root/'evidence.json').write_text(json.dumps(evidence,ensure_ascii=False,indent=2),encoding='utf-8')


@pytest.mark.process
def test_real_http_cli_lost_receipt_and_background_completion():
    paths,runs,jobs,port=make_root('http-cli',count=20)
    evidence={'root':str(paths.root),'commands':[]}
    def cli(command,body,crash=False,action='request'):
        path=paths.root/(uuid.uuid4().hex+'.json');path.write_text(json.dumps(body),encoding='utf-8')
        args=[sys.executable,'-m','tests.client.invoke' if crash else 'fashion_scout.client',action]
        if command:args.append(command)
        args+=['--data-root',str(paths.root),'--json-input',str(path)]
        result=subprocess.run(args,cwd=ROOT,capture_output=True,text=True,encoding='utf-8',timeout=30)
        assert result.returncode==(73 if crash else 0),(result.stdout,result.stderr)
        value=None if crash else json.loads(result.stdout)
        evidence['commands'].append({'command':command or action,'exit':result.returncode,'result':value})
        return value
    try:
        # Launcher parent exits completely; original Worker/Web remain independently hosted.
        started=subprocess.run([sys.executable,'-m','fashion_scout.launcher','ensure','--data-root',str(paths.root),'--port',str(port),'--json'],cwd=ROOT,capture_output=True,text=True,timeout=30)
        assert started.returncode==0
        cli(None,{'port':port},action='configure')
        cli('export',{'new_intent':True},crash=True)
        intent=next(x for x in cli('intents',{})['data']['items'] if x['command']=='export')
        resumed=cli('resume',{'intent_id':intent['intent_id']})['data']['result']
        jid=resumed['export']['id'];assert resumed['reused']
        wait(lambda:jobs.get(jid)['state'] in {'succeeded','partial'})
        result=cli('export-status',{'export_id':jid})
        assert result['data']['export']['state']=='partial'
        cli('export-retry',{'new_intent':True,'export_id':jid},crash=True)
        intent=next(x for x in cli('intents',{})['data']['items'] if x['command']=='export-retry')
        cli('resume',{'intent_id':intent['intent_id']})
        wait(lambda:jobs.get(jid)['state']=='partial')
        assert jobs.get(jid)['attempt']==2
        from fashion_scout.client import Connection
        conn=Connection(paths,port)
        # HTTP binary download uses the verified controlled URL without exposing credentials.
        conn.verify()
        import httpx,hashlib
        with httpx.Client(trust_env=False,follow_redirects=False) as http:
            response=http.get(f'http://127.0.0.1:{port}/v1/exports/{jid}/download',headers={'Authorization':'Bearer '+conn.token})
        assert response.status_code==200 and hashlib.sha256(response.content).hexdigest()==jobs.get(jid)['sha256']
        with jobs.db.read() as db:
            assert db.execute('SELECT COUNT(*) FROM export_jobs').fetchone()[0]==1
            assert db.execute('SELECT COUNT(*) FROM export_attempts').fetchone()[0]==2
            assert db.execute('SELECT COUNT(*) FROM collection_http').fetchone()[0]==0
            assert db.execute('SELECT COUNT(*) FROM runs').fetchone()[0]==1
        evidence.update(source_requests=0,job_count=1,attempt_count=2,download_sha256=hashlib.sha256(response.content).hexdigest())
    finally:
        if launcher.read_descriptor(paths):evidence['stop']=launcher.stop(paths)
        (paths.root/'evidence.json').write_text(json.dumps(evidence,ensure_ascii=False,indent=2),encoding='utf-8')


@pytest.mark.process
def test_web_exit_does_not_stop_accepted_export_or_heartbeat():
    import httpx
    paths,runs,jobs,port=make_root('web-exit')
    launcher.ensure(paths,port);descriptor=launcher.read_descriptor(paths)
    worker=launcher.verified_process(paths,descriptor,'worker');worker.terminate();worker.wait(timeout=5)
    helper=subprocess.Popen([sys.executable,'-m','tests.integration.export_process_helper',str(paths.root),'during_copy'],cwd=ROOT,
        stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,creationflags=subprocess.CREATE_NO_WINDOW)
    evidence={'root':str(paths.root),'scenario':'web-exits-during-asset-copy'}
    try:
        token=(paths.root/'control'/(descriptor['instance']+'.key')).read_text('ascii')
        with httpx.Client(trust_env=False) as client:
            response=client.post(f'http://127.0.0.1:{port}/v1/exports',json={'request_key':'web-exit','selection':'favorites'},headers={'Authorization':'Bearer '+token})
        assert response.status_code==202;jid=response.json()['export']['id']
        wait((paths.root/'export-paused.json').exists)
        with jobs.db.read() as conn:before=dict(jobs.row(conn,jid))
        web=launcher.verified_process(paths,descriptor,'web');web.terminate();web.wait(timeout=5)
        def heartbeat_advanced():
            with jobs.db.read() as conn:return jobs.row(conn,jid)['heartbeat_at']>before['heartbeat_at']
        wait(heartbeat_advanced,seconds=8)
        (paths.root/'export-release').touch()
        done=wait(lambda: (s if (s:=jobs.get(jid))['state']=='partial' else None))
        stream,size=jobs.download(jid);assert stream.read(2)==b'PK';stream.close()
        with jobs.db.read() as conn:
            assert conn.execute('SELECT COUNT(*) FROM export_jobs').fetchone()[0]==1
            assert conn.execute('SELECT COUNT(*) FROM collection_http').fetchone()[0]==0
        evidence.update(export=done,heartbeat_advanced_while_copy_paused=True,web_verified_dead=True,source_requests=0)
    finally:
        (paths.root/'export-stop').touch();helper.wait(timeout=10)
        evidence['stop']=launcher.stop(paths)
        (paths.root/'evidence.json').write_text(json.dumps(evidence,ensure_ascii=False,indent=2),encoding='utf-8')
