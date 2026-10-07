"""Installed local processes + fixed CLI; all source observations/media are synthetic."""
import hashlib
import json
import socket
import subprocess
import sys
import time
import uuid
import zipfile
from pathlib import Path
import pytest
from fashion_scout import launcher
from fashion_scout.config import Paths
from fashion_scout.db import Database
from fashion_scout.exports.jobs import Jobs
from fashion_scout.media.browser_intake import native_base
from fashion_scout.services.runs import Runs
from .test_bridge import PRODUCT,image_bytes

ROOT=Path(__file__).resolve().parents[2]


@pytest.mark.process
def test_independent_worker_wait_export_and_same_run_receipt_recovery():
    root=ROOT/'.runtime'/('t2-browser-process-'+uuid.uuid4().hex[:12]);root.mkdir(parents=True)
    paths=Paths.at(root);runs=Runs(Database(paths.db))
    with socket.socket() as sock:sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
    evidence={'synthetic_only':True,'source_network_requests':0,'root':str(root),'port':port,'commands':[]}
    def call(command,payload,configure=False,crash=False,expected=0):
        input_file=root/('input-'+uuid.uuid4().hex+'.json');input_file.write_text(json.dumps(payload),encoding='utf-8')
        module='tests.browser_acquisition.lose_upload_receipt' if crash else 'fashion_scout.client'
        args=[sys.executable,'-m',module,'configure' if configure else 'request']
        if not configure:args.append(command)
        args+=['--data-root',str(root),'--json-input',str(input_file)]
        completed=subprocess.run(args,cwd=ROOT,capture_output=True,text=True,encoding='utf-8',timeout=30)
        assert completed.returncode==expected,(command,completed.returncode,completed.stdout,completed.stderr)
        assert not completed.stderr
        if crash:
            assert not completed.stdout
            evidence['commands'].append({'command':command,'exit':73,'fault':'exit after complete upload response'})
            return
        value=json.loads(completed.stdout)
        for private in (root/'control').glob('*.key'):assert private.read_text('ascii') not in completed.stdout
        assert '/bootstrap#' not in completed.stdout
        evidence['commands'].append({'command':command or 'configure','exit':expected,'result':value})
        return value['data'] if expected==0 else value
    def until(check,timeout=25):
        end=time.monotonic()+timeout
        while time.monotonic()<end:
            value=check()
            if value:return value
            time.sleep(.2)
        raise AssertionError('Local process did not reach expected state')
    native_directory=native_base()/str(uuid.uuid4())
    try:
        call(None,{'port':port},configure=True);call('ensure',{})
        assert call('latest',{})['latest_run'] is None
        plan=call('default-plan',{})
        call('set-default-plan',{'expected_revision':plan['revision'],'network':{**plan['plan']['network'],'run_total_seconds':1}})
        accepted=call('start',{'new_intent':True,'overrides':{'source_mode':'browser','browser':{'idle_seconds':10}}})['result']
        rid=accepted['run']['id'];source=call('browser-attach',{'new_intent':True,'run_id':rid})['result'];sid=source['session_id']
        call('browser-observe',{'new_intent':True,'run_id':rid,'session_id':sid,'observation':{'kind':'listing','page_url':'https://futario.com/collections/new-in','pass_number':1,'page_number':1,'terminal':False,'products':[PRODUCT]}})
        url='https://futario.com/cdn/shop/files/process-synthetic.png?width=1080'
        call('browser-observe',{'new_intent':True,'run_id':rid,'session_id':sid,'observation':{'kind':'detail','product':PRODUCT,'images':[{'source_image_id':'0','url':url,'ordinal':0}],'gallery_end_observed':True,'expected_count':1}})
        def get_ticket():
            value=call('browser-status',{'run_id':rid})['tickets']
            return value[0] if value else None
        ticket=until(get_ticket)
        native_directory.mkdir(parents=True);data=image_bytes();file=native_directory/'selected.png';file.write_bytes(data)
        manifest=native_directory/'manifest.json'
        manifest.write_text(json.dumps({'assets':[{'id':'synthetic-native','path':str(file),'url':url,'kind':'image','contentType':'image/webp'}],'failures':[]}),encoding='utf-8')
        upload={'new_intent':True,'run_id':rid,'session_id':sid,'ticket_id':ticket['id'],
                'native_directory':str(native_directory),'manifest_path':str(manifest),'asset_id':'synthetic-native',
                'source_url':url,'sha256':hashlib.sha256(data).hexdigest(),'bytes':len(data)}
        call('browser-upload',upload,crash=True,expected=73)
        pending=next(x for x in call('intents',{})['items'] if x['command']=='browser-upload')
        assert pending['state']=='sending'
        file.unlink()  # Received receipt remains recoverable after the host asset disappears.
        receipt=call('resume',{'intent_id':pending['intent_id']})['result']
        assert receipt['sha256']==upload['sha256'] and receipt['state']=='received'
        until(lambda:runs.get(rid).state=='interrupted')
        assert runs.get(rid).issue_code=='SOURCE_HOST_REQUIRED'
        descriptor=launcher.read_descriptor(paths);process=launcher.verified_process(paths,descriptor,'worker')
        assert process and process.pid!=__import__('os').getpid()
        first_epoch=runs.get(rid).epoch
        call('ensure',{});assert runs.get(rid).epoch==first_epoch
        product=call('product',{'product_id':'futario-'+PRODUCT['source_id']})['product']
        assert product['latest_observed_album']['stored_count']==1
        call('user-state',{'product_id':product['id'],'expected_revision':product['user_state']['revision'],'favorite':True})
        jid=call('export',{'new_intent':True})['result']['export']['id']
        def done_export():
            value=call('export-status',{'export_id':jid})['export']
            return value if value['state'] in ('partial','succeeded','failed') else None
        result=until(done_export)
        assert result['state']=='partial' and result['unknown_count']>=1
        with runs.db.read() as conn:
            assert conn.execute('SELECT owner FROM export_jobs WHERE id=?',(jid,)).fetchone()[0]==conn.execute('SELECT id FROM workers WHERE pid=?',(process.pid,)).fetchone()[0]
        stream,_=Jobs(paths).download(jid)
        with stream,zipfile.ZipFile(stream) as package:
            package_manifest=json.loads(package.read('manifest.json'))
            image_names=[n for n in package.namelist() if '/images/' in n]
            assert len(image_names)==1 and hashlib.sha256(package.read(image_names[0])).hexdigest()==upload['sha256']
        call('browser-observe',{'new_intent':True,'run_id':rid,'session_id':sid,'observation':{'kind':'finish'}},expected=4)
        continued=call('browser-continue',{'new_intent':True,'run_id':rid})['result']
        assert continued['same_run'] and continued['run_id']==rid
        sid2=call('browser-attach',{'new_intent':True,'run_id':rid})['result']['session_id']
        assert sid2!=sid
        call('browser-observe',{'new_intent':True,'run_id':rid,'session_id':sid2,'observation':{'kind':'finish'}})
        until(lambda:runs.get(rid).state=='partial')
        with runs.db.read() as conn:
            assert conn.execute('SELECT COUNT(*) FROM runs').fetchone()[0]==1
            assert conn.execute('SELECT COUNT(*) FROM collection_http').fetchone()[0]==0
            assert conn.execute('SELECT COUNT(*) FROM assets').fetchone()[0]==1
            assert conn.execute('SELECT COUNT(*) FROM archive_journal WHERE state=\'committed\'').fetchone()[0]==1
            assert conn.execute('SELECT attempts FROM work_items').fetchone()[0]==1
            evidence['archive']=[dict(r) for r in conn.execute('SELECT sha256,bytes,format,width,height FROM assets')]
        evidence.update(run_id=rid,worker_pid=process.pid,export_id=jid,export_manifest=package_manifest,
                        same_run_attempt=runs.get(rid).attempt,independent_worker=True,source_wait_did_not_spend_processing_clock=True)
    finally:
        if launcher.read_descriptor(paths):launcher.stop(paths)
        if native_directory.parent==native_base() and str(uuid.UUID(native_directory.name))==native_directory.name:
            import shutil
            if native_directory.exists():shutil.rmtree(native_directory)
        (root/'evidence.json').write_text(json.dumps(evidence,ensure_ascii=False,indent=2),encoding='utf-8')
