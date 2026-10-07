"""Real launcher + real local HTTP, isolated .runtime/t4-* only; no source I/O."""
import json
from pathlib import Path
import socket
import subprocess
import sys
import uuid
from unittest.mock import patch
import pytest
from fashion_scout import client as c, launcher
from fashion_scout.config import Paths
from fashion_scout.db import Database
from fashion_scout.services.runs import Runs
from tests.api.helpers import seed

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.process
def test_real_cli_lifecycle_and_cross_process_recovery():
    root=ROOT/'.runtime'/('t5c-t4-regression-'+uuid.uuid4().hex[:12])
    paths=Paths.at(root)
    with socket.socket() as sock:
        sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
    evidence={'root':str(root),'port':port,'commands':[],'real_http':True,'source_requests':None}
    def call(command,payload,action='request',crash=False,expected=0):
        input_file=root/('input-'+uuid.uuid4().hex+'.json')
        root.mkdir(parents=True,exist_ok=True)
        input_file.write_text(json.dumps(payload),encoding='utf-8')
        args=[sys.executable,'-m','tests.client.invoke' if crash else 'fashion_scout.client',action]
        if command:args.append(command)
        args+=['--data-root',str(root),'--json-input',str(input_file)]
        proc=subprocess.run(args,cwd=ROOT,capture_output=True,text=True,encoding='utf-8',timeout=30)
        assert proc.returncode==expected,(proc.returncode,proc.stdout,proc.stderr)
        assert not proc.stderr
        if crash:
            assert not proc.stdout
            evidence['commands'].append({'command':command,'exit':73,'fault':'process exit after real API response'})
            return
        data=json.loads(proc.stdout)
        assert data['exit_code']==expected
        for key in (root/'control').glob('*.key'):
            assert key.read_text('ascii') not in proc.stdout
        assert '/bootstrap#' not in proc.stdout
        evidence['commands'].append({'command':command or action,'exit':expected,'response':data})
        return data
    try:
        call(None,{'port':port},action='configure')
        assert not paths.db.exists()  # configure is not a business DB operation.
        assert call('latest',{},expected=3)['error']['code']=='SERVICE_OFFLINE'
        started=call('ensure',{})
        assert started['data']['resuming_run_ids']==[]
        assert call('latest',{})['data']['latest_run'] is None
        assert call('new',{})['data']['total']==0
        # Real launcher/open/bootstrap route, only OS browser invocation intercepted.
        with patch('webbrowser.open',return_value=True) as browser:
            opened=c.Client(paths).execute('open',{})
            assert opened['browser_opened'] and browser.call_count==1
        runs=Runs(Database(paths.db))
        with runs.db.read() as db:
            assert db.execute('SELECT COUNT(*) FROM runs').fetchone()[0]==0
            assert db.execute('SELECT COUNT(*) FROM collection_http').fetchone()[0]==0
        seed(runs,paths,count=4)  # atomic terminal-only synthetic fixture
        assert call('new',{})['data']['total']==4
        call('sites',{})
        before=call('default-plan',{})['data']
        product=call('product',{'product_id':'fixture-000'})['data']['product']
        rev=product['user_state']['revision']
        call('user-state',{'product_id':'fixture-000','expected_revision':rev,'favorite':True,'category_override':'tops'})
        assert call('favorites',{})['data']['total']==1
        assert call('product',{'product_id':'fixture-000'})['data']['product']['effective_category']=='tops'
        conflict=call('user-state',{'product_id':'fixture-000','expected_revision':rev,'favorite':False},expected=4)
        assert conflict['error']['code']=='REVISION_CONFLICT'
        with runs.db.read() as db:
            assert db.execute('SELECT COUNT(*) FROM view_events').fetchone()[0]==0
        # No accepted active work exists. Stop precisely the verified isolated Worker.
        descriptor=launcher.read_descriptor(paths)
        worker=launcher.verified_process(paths,descriptor,'worker')
        assert worker is not None
        worker.terminate();worker.wait(timeout=10)
        assert launcher.verified_process(paths,descriptor,'worker') is None
        evidence['worker_stopped_before_explicit_run']=True
        call('start',{'new_intent':True,'overrides':{'window_days':7}},crash=True,expected=73)
        intents=call('intents',{})['data']['items']
        pending=next(x for x in intents if x['command']=='start' and x['state']=='sending')
        recovered=call('resume',{'intent_id':pending['intent_id']})['data']['result']
        run_id=recovered['run']['id']
        assert recovered['reconciled_by_request'] and recovered['run']['snapshot']['window_days']==7
        assert call('default-plan',{})['data']['revision']==before['revision']
        assert call('default-plan',{})['data']['plan']==before['plan']
        second=call('start',{'new_intent':True,'overrides':{'window_days':14}})['data']['result']
        assert second['reused'] and second['reuse_reason']=='active_run'
        assert second['ignored_overrides']==['window_days'] and second['run']['id']==run_id
        # Server itself rejects the original key with different payload; no replacement key.
        conn=c.Connection(paths,port)
        status,data=conn.request('POST','/v1/runs',{'request_key':pending['payload']['request_key'],'trigger':'skill','overrides':{'window_days':14}})
        assert status==409 and data['error']['code']=='REQUEST_KEY_CONFLICT'
        call('cancel',{'new_intent':True,'run_id':run_id},crash=True,expected=73)
        pending_cancel=next(x for x in call('intents',{})['data']['items'] if x['command']=='cancel')
        cancelled=call('resume',{'intent_id':pending_cancel['intent_id']})['data']['result']['run']
        assert cancelled['state']=='cancelled'
        # Terminal same-key replay stays on the original run and returns its present state.
        status,data=conn.request('POST','/v1/runs',pending['payload'])
        assert status==200 and data['run']['id']==run_id and data['run']['state']=='cancelled'
        assert data['reuse_reason']=='request_key'
        call('retry',{'new_intent':True,'run_id':run_id},crash=True,expected=73)
        pending_retry=next(x for x in call('intents',{})['data']['items'] if x['command']=='retry')
        retried=call('resume',{'intent_id':pending_retry['intent_id']})['data']['result']['run']
        assert retried['id']==run_id and retried['state']=='queued' and retried['attempt']==2
        call('cancel',{'new_intent':True,'run_id':run_id})
        current=call('progress',{'run_id':run_id})
        assert current['service']['worker_state']=='offline' and current['data']['run']['state']=='cancelled'
        call('set-default-plan',{'expected_revision':before['revision'],'window_days':7})
        assert call('set-default-plan',{'expected_revision':before['revision'],'window_days':14},expected=4)['error']['code']=='REVISION_CONFLICT'
        # Uncertain CAS never gets automatically replayed in a fresh client process.
        revision=call('default-plan',{})['data']['revision']
        call('set-default-plan',{'expected_revision':revision,'window_days':14},crash=True,expected=73)
        uncertain=next(x for x in call('intents',{})['data']['items'] if x['command']=='set-default-plan' and x['state']=='sending')
        assert call('resume',{'intent_id':uncertain['intent_id']},expected=4)['error']['code']=='CAS_REVIEW_REQUIRED'
        assert call('default-plan',{})['data']['revision']==revision+1
        for command in ('maintenance','storage'):call(command,{})
        with runs.db.read() as db:
            evidence['source_requests']=db.execute('SELECT COUNT(*) FROM collection_http').fetchone()[0]
            evidence['run_count']=db.execute('SELECT COUNT(*) FROM runs').fetchone()[0]
            evidence['run_request_count']=db.execute('SELECT COUNT(*) FROM run_requests').fetchone()[0]
            evidence['view_events']=db.execute('SELECT COUNT(*) FROM view_events').fetchone()[0]
        assert evidence['source_requests']==0 and evidence['run_count']==2 and evidence['run_request_count']==2
    finally:
        if launcher.read_descriptor(paths):
            evidence['stop']=launcher.stop(paths)
            evidence['after_stop']=launcher.status(paths)
        (root/'integration-evidence.json').write_text(json.dumps(evidence,ensure_ascii=False,indent=2),encoding='utf-8')

