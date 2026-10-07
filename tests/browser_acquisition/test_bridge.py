"""Synthetic DOM facts/files enter through the production API and Archive, never SQL source seeding."""
import hashlib
import io
import json
import time
import uuid
from PIL import Image
from fashion_scout.domain.models import CreateRun, Overrides, run_request_payload
from fashion_scout.services.runs import canonical, digest
from .conftest import eventually,worker

PRODUCT={'source_id':'15394260681068','handle':'synthetic-cardigan','url':'https://futario.com/products/synthetic-cardigan','title':'Synthetic browser cardigan'}


def key():return uuid.uuid4().hex
def ok(response):
    assert response.status_code<400,response.text
    return response.json()


def accepted(client,*,idle=5,active=60,policy='include',caps=None):
    limits={'idle_seconds':idle,**(caps or {})}
    # The defaults are changed through the normal API before this explicit Run.
    current=ok(client.get('/v1/settings/default-plan'))
    network={**current['plan']['network'],'run_total_seconds':active}
    ok(client.patch('/v1/settings/default-plan',json={'expected_revision':current['revision'],'network':network}))
    value=ok(client.post('/v1/runs',json={'request_key':key(),'trigger':'skill','overrides':{'source_mode':'browser','browser':limits,'unknown_date_policy':policy}}))
    rid=value['run']['id'];prefix='/v1/runs/'+rid+'/browser-source'
    attached=ok(client.post(prefix+'/attach',json={'request_key':key()}))
    return rid,prefix,attached['session_id']


def observe(client,prefix,sid,fact,request_key=None):
    return ok(client.post(prefix+'/observations',json={'request_key':request_key or key(),'session_id':sid,'observation':fact}))


def listing(client,prefix,sid,number=1,terminal=False):
    return observe(client,prefix,sid,{'kind':'listing','page_url':'https://futario.com/collections/new-in','pass_number':number,'page_number':1,'terminal':terminal,'products':[PRODUCT]})


def detail(client,prefix,sid,count=6,complete=True):
    return observe(client,prefix,sid,{'kind':'detail','product':PRODUCT,'images':[{'source_image_id':str(n),'url':f'https://futario.com/cdn/shop/files/synthetic-{n}.png?width=1080','ordinal':n} for n in range(count)],'gallery_end_observed':complete,'expected_count':count if complete else None,'observed_options':['Brown','XS','S','M','L','XL','2XL']})


def image_bytes(n=0):
    output=io.BytesIO();Image.new('RGB',(24,32),(n*31%256,80,140)).save(output,'WEBP')
    return output.getvalue()


def upload(client,prefix,sid,ticket,data=None,request_key=None,sha=None):
    data=data or image_bytes(int(ticket['source_image_id']))
    return client.post(prefix+'/assets/'+ticket['id']+'/body',content=data,headers={
        'Content-Type':'application/octet-stream','X-Source-Session':sid,'X-Request-Key':request_key or key(),
        'X-Source-Sha256':sha or hashlib.sha256(data).hexdigest(),'X-Source-Bytes':str(len(data)),'X-Source-Url':ticket['source_url']})


def status(client,prefix):return ok(client.get(prefix))


def tickets(client,prefix,count=6):
    return eventually(lambda:(s['tickets'] if len((s:=status(client,prefix))['tickets'])==count else None))


def finish(client,prefix,sid):return observe(client,prefix,sid,{'kind':'finish'})


def test_six_enumerated_five_archived_stays_partial_and_exports_scope(env):
    client,runs,paths,app=env
    with worker(paths):
        rid,prefix,sid=accepted(client)
        listing(client,prefix,sid);detail(client,prefix,sid)
        all_tickets=tickets(client,prefix)
        for ticket in all_tickets[:5]:ok(upload(client,prefix,sid,ticket))
        finish(client,prefix,sid)
        eventually(lambda:runs.get(rid).state=='partial')
        product=ok(client.get('/v1/products/futario-'+PRODUCT['source_id']))['product']
        album=product['latest_observed_album']
        assert album['coverage_scope']==['browser.gallery']
        assert album['expected_count']==6 and album['stored_count']==5 and not album['coverage_complete']
        assert any(n['scope']=='product.images' and n['status']=='unknown' for n in album['capability_notes'])
        ok(client.patch('/v1/products/'+product['id']+'/user-state',json={'expected_revision':product['user_state']['revision'],'favorite':True}))
        job=ok(client.post('/v1/exports',json={'request_key':key(),'selection':'favorites'}))
        jid=job['export']['id']
        export=eventually(lambda: (v if (v:=ok(client.get('/v1/exports/'+jid)))['export']['state'] in ('partial','succeeded','failed') else None))['export']
        assert export['state']=='partial' and export['missing_count']==1
        import zipfile
        with zipfile.ZipFile(io.BytesIO(client.get(export['download_url']).content)) as package:
            manifest=json.loads(package.read('manifest.json'))
            assert manifest['schema_version']==2 and manifest['products'][0]['coverage']['scope']=='browser.gallery'
            assert len([n for n in package.namelist() if '/images/' in n])==5
        with runs.db.read() as conn:
            assert conn.execute('SELECT COUNT(*) FROM collection_http').fetchone()[0]==0
            assert conn.execute('SELECT COUNT(*) FROM archive_journal WHERE state=\'committed\'').fetchone()[0]==5


def test_complete_browser_scope_keeps_full_api_capabilities_unknown(env):
    client,runs,paths,app=env
    with worker(paths):
        rid,prefix,sid=accepted(client)
        listing(client,prefix,sid,1,True);listing(client,prefix,sid,2,True);detail(client,prefix,sid,1)
        ok(upload(client,prefix,sid,tickets(client,prefix,1)[0]))
        finish(client,prefix,sid)
        eventually(lambda:runs.get(rid).state=='partial')
        value=ok(client.get('/v1/runs/'+rid))['run']
        assert value['coverage'][0]['media_scope']=='browser.gallery'
        assert value['issue_code']=='SOURCE_SCOPE_UNKNOWN'
        assert value['snapshot']['adapter_versions']['futario']=='futario-browser-host-v1'
        assert value['browser_source']['network_accounting'].endswith('_unknown')


def test_same_run_continue_retains_completed_assets_and_rejects_old_session(env):
    client,runs,paths,app=env
    with worker(paths) as execution:
        rid,prefix,sid=accepted(client,idle=1,active=1)
        listing(client,prefix,sid);detail(client,prefix,sid,2)
        original=tickets(client,prefix,2)
        ok(upload(client,prefix,sid,original[0]))
        eventually(lambda:any(t['state']=='archived' for t in status(client,prefix)['tickets']))
        eventually(lambda:runs.get(rid).state=='interrupted')
        epoch=runs.get(rid).epoch
        time.sleep(1.1)
        assert runs.get(rid).epoch==epoch and runs.get(rid).issue_code=='SOURCE_HOST_REQUIRED'
        continued=ok(client.post(prefix+'/continue',json={'request_key':key()}))
        assert continued['same_run'] and continued['run_id']==rid
        sid2=ok(client.post(prefix+'/attach',json={'request_key':key()}))['session_id']
        assert sid2!=sid
        stale=upload(client,prefix,sid,original[1])
        assert stale.status_code==409 and stale.json()['error']['code']=='STALE_SOURCE_SESSION'
        ok(upload(client,prefix,sid2,original[1]));finish(client,prefix,sid2)
        eventually(lambda:runs.get(rid).state=='partial')
        with runs.db.read() as conn:
            assert conn.execute('SELECT COUNT(*) FROM runs').fetchone()[0]==1
            assert conn.execute('SELECT COUNT(*) FROM archive_journal WHERE state=\'committed\'').fetchone()[0]==2
            assert conn.execute('SELECT MAX(attempts) FROM work_items').fetchone()[0]==1


def test_excluded_unknown_dates_never_issue_media_tickets(env):
    client,runs,paths,app=env
    with worker(paths):
        rid,prefix,sid=accepted(client,policy='exclude')
        listing(client,prefix,sid);detail(client,prefix,sid,1);finish(client,prefix,sid)
        eventually(lambda:runs.get(rid).state in ('failed','partial','succeeded'))
        value=status(client,prefix)
        assert not value['tickets'] and not value['products'][0]['eligible']
        assert all(m['state']=='applied' for m in value['messages'])


def test_auth_schema_conflicting_keys_and_cancellation(env):
    client,runs,paths,app=env
    rid,prefix,sid=accepted(client)
    assert client.get(prefix,headers={'Authorization':''}).status_code==401
    before=status(client,prefix)
    assert not before['tickets']
    assert client.post(prefix+'/observations',json={'request_key':key(),'session_id':sid,'observation':{'kind':'finish','succeeded':True}}).status_code==422
    k=key();first=listing(client,prefix,sid)
    fact={'kind':'finish'}
    one=observe(client,prefix,sid,fact,k)
    assert observe(client,prefix,sid,fact,k)['message_id']==one['message_id']
    assert client.post(prefix+'/observations',json={'request_key':k,'session_id':sid,'observation':{'kind':'listing','page_url':'https://futario.com/collections/new-in','pass_number':1,'page_number':1,'terminal':True,'products':[]}}).status_code==409
    ok(client.post('/v1/runs/'+rid+'/cancel',json={'request_key':key()}))
    assert client.post(prefix+'/attach',json={'request_key':key()}).status_code==409
    assert client.post(prefix+'/observations',json={'request_key':key(),'session_id':sid,'observation':fact}).status_code==409


def test_old_http_hash_response_and_active_mode_remain_compatible(env):
    client,runs,paths,app=env
    request={'request_key':key(),'trigger':'skill','overrides':{}}
    first=ok(client.post('/v1/runs',json=request))
    legacy={'trigger':'skill','overrides':{'site_ids':None,'window_days':None,'unknown_date_policy':None}}
    with runs.db.read() as conn:
        row=conn.execute('SELECT * FROM run_requests WHERE request_key=?',(request['request_key'],)).fetchone()
        saved=row['response_json'];assert row['payload_hash']==digest(legacy)
    assert 'source_mode' not in first['run']['snapshot'] and 'browser' not in first['run']['snapshot']
    replay=ok(client.post('/v1/runs',json=request))
    assert replay['run']['id']==first['run']['id'] and replay['reuse_reason']=='request_key'
    with runs.db.read() as conn:assert conn.execute('SELECT response_json FROM run_requests WHERE request_key=?',(request['request_key'],)).fetchone()[0]==saved
    assert client.post('/v1/runs',json={**request,'overrides':{'source_mode':'browser'}}).status_code==409
    assert client.post('/v1/runs',json={'request_key':key(),'trigger':'skill','overrides':{'source_mode':'browser'}}).json()['error']['code']=='SOURCE_MODE_CONFLICT'
    assert client.post('/v1/runs/'+first['run']['id']+'/browser-source/attach',json={'request_key':key()}).status_code==409


def test_upload_hash_url_pixel_and_cumulative_caps(env):
    client,runs,paths,app=env
    with worker(paths):
        rid,prefix,sid=accepted(client,caps={'max_selected_assets':1,'max_received_bytes':1024})
        listing(client,prefix,sid);detail(client,prefix,sid,2)
        choices=tickets(client,prefix,2)
        bad=upload(client,prefix,sid,choices[0],sha='0'*64)
        assert bad.status_code==422
        assert status(client,prefix)['received_bytes']>0
        over=upload(client,prefix,sid,choices[1])
        assert over.status_code==409 and over.json()['error']['code']=='SOURCE_ASSET_BUDGET'
        finish(client,prefix,sid)
        eventually(lambda:runs.get(rid).state=='failed')
