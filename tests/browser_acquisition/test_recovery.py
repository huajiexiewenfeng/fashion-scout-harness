import asyncio
import hashlib
import json
import pytest
from fashion_scout.db.archive import Archive
from fashion_scout.media.browser_intake import BrowserIntake
from fashion_scout.worker import StopRequested
from .conftest import eventually,worker
from .test_bridge import accepted,listing,detail,tickets,upload,image_bytes,finish,key,ok,status


@pytest.mark.parametrize('boundary',['stage','commit'])
def test_actual_archive_interruption_recovers_same_run_once(env,monkeypatch,boundary):
    client,runs,paths,app=env
    original=getattr(Archive,boundary)
    interrupted=[]
    def fault(self,*args,**kwargs):
        result=original(self,*args,**kwargs)
        if not interrupted:
            interrupted.append(result)
            raise StopRequested()
        return result
    monkeypatch.setattr(Archive,boundary,fault)
    with worker(paths):
        rid,prefix,sid=accepted(client)
        listing(client,prefix,sid);detail(client,prefix,sid,1)
        ticket=tickets(client,prefix,1)[0]
        ok(upload(client,prefix,sid,ticket))
        eventually(lambda:runs.get(rid).state=='interrupted')
    assert interrupted
    monkeypatch.setattr(Archive,boundary,original)
    ok(client.post(prefix+'/continue',json={'request_key':key()}))
    sid2=ok(client.post(prefix+'/attach',json={'request_key':key()}))['session_id']
    with worker(paths):
        finish(client,prefix,sid2)
        eventually(lambda:runs.get(rid).state=='partial')
    with runs.db.read() as conn:
        assert conn.execute('SELECT COUNT(*) FROM runs').fetchone()[0]==1
        assert conn.execute('SELECT COUNT(*) FROM assets').fetchone()[0]==1
        assert conn.execute('SELECT COUNT(*) FROM archive_journal').fetchone()[0]==1
        assert conn.execute('SELECT state FROM archive_journal').fetchone()[0]=='committed'
        assert conn.execute('SELECT attempts FROM work_items').fetchone()[0]==1
    assert status(client,prefix)['tickets'][0]['state']=='archived'


def test_stream_interrupted_before_receipt_is_bounded_and_replayed_same_key(env):
    client,runs,paths,app=env
    with worker(paths):
        rid,prefix,sid=accepted(client)
        listing(client,prefix,sid);detail(client,prefix,sid,1)
        ticket=tickets(client,prefix,1)[0];data=image_bytes();request_key=key()
        intake=BrowserIntake(paths,runs)
        transfer=intake.begin(rid,ticket['id'],sid,request_key,hashlib.sha256(data).hexdigest(),len(data),ticket['source_url'])
        class Disconnect:
            async def stream(self):
                yield data[:len(data)//2]
                raise ConnectionError('synthetic disconnect')
        with pytest.raises(ConnectionError):asyncio.run(intake.receive(Disconnect(),transfer))
        assert intake.path(transfer['relative']).stat().st_size==len(data)//2
        with runs.db.read() as conn:assert conn.execute('SELECT COUNT(*) FROM assets').fetchone()[0]==0
        ok(upload(client,prefix,sid,ticket,data,request_key=request_key))
        finish(client,prefix,sid)
        eventually(lambda:runs.get(rid).state=='partial')
        value=status(client,prefix)
        assert value['selected_assets']==1 and value['received_bytes']==len(data)+len(data)//2
        receipt=ok(client.get(prefix+'/receipts/'+request_key))
        assert receipt['state']=='received' and receipt['sha256']==hashlib.sha256(data).hexdigest()
        assert client.post(prefix+'/assets/'+ticket['id']+'/body',json={'path':str(intake.path(transfer['relative']))}).status_code==422


def test_invalid_image_and_pixels_are_worker_decisions(env):
    client,runs,paths,app=env
    current=ok(client.get('/v1/settings/default-plan'))
    storage={**current['plan']['storage'],'max_pixels':10}
    ok(client.patch('/v1/settings/default-plan',json={'expected_revision':current['revision'],'storage':storage}))
    with worker(paths):
        rid,prefix,sid=accepted(client)
        listing(client,prefix,sid);detail(client,prefix,sid,2)
        choices=tickets(client,prefix,2)
        ok(upload(client,prefix,sid,choices[0],data=b'not an image'))
        ok(upload(client,prefix,sid,choices[1],data=image_bytes(1)))
        finish(client,prefix,sid)
        eventually(lambda:runs.get(rid).state=='failed')
        assert all(t['state']=='failed' for t in status(client,prefix)['tickets'])
        with runs.db.read() as conn:
            assert conn.execute('SELECT COUNT(*) FROM assets').fetchone()[0]==0
            assert conn.execute('SELECT COUNT(*) FROM archive_journal').fetchone()[0]==0
