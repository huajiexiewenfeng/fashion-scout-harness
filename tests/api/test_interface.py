import hashlib
import json
import pytest
from fastapi.testclient import TestClient
from fashion_scout.health import create_app
from fashion_scout.services.runs import digest, canonical
from .helpers import seed


def db_hash(runs):
    with runs.db.read() as conn:
        return hashlib.sha256('\n'.join(conn.iterdump()).encode()).hexdigest()


def test_auth_host_origin_csrf_bootstrap_one_use(api_env):
    client, app, runs, paths, token=api_env
    with TestClient(app,base_url='http://127.0.0.1:18765') as browser:
        assert browser.get('/v1/products').status_code==401
        assert client.get('/v1/products',headers={'Host':'evil.example'}).status_code==400
        assert client.post('/v1/runs',headers={'Origin':'https://evil.example'},json={'request_key':'x','trigger':'ui'}).status_code==403
        grant=client.post('/v1/session/bootstrap',json={}).json()
        assert token not in json.dumps(grant)
        code=grant['bootstrap_url'].split('#')[1]
        assert browser.post('/v1/session/exchange',json={'code':code}).status_code==403
        response=browser.post('/v1/session/exchange',headers={'Origin':'http://127.0.0.1:18765'},json={'code':code})
        assert response.status_code==200
        cookie=response.headers['set-cookie']
        assert 'HttpOnly' in cookie and 'SameSite=strict' in cookie and 'Secure' not in cookie
        assert browser.post('/v1/session/exchange',headers={'Origin':'http://127.0.0.1:18765'},json={'code':code}).status_code==401
        assert browser.get('/v1/products').status_code==200
        csrf=browser.get('/v1/session').json()['csrf_token']
        body={'request_key':'browser-intent','trigger':'ui'}
        assert browser.post('/v1/runs',json=body).status_code==403
        assert browser.post('/v1/runs',headers={'X-CSRF-Token':csrf},json=body).status_code==403
        response=browser.post('/v1/runs',headers={'X-CSRF-Token':csrf,'Origin':'http://127.0.0.1:18765'},json=body)
        assert response.status_code==202
        assert 'access-control-allow-origin' not in response.headers
        assert 'frame-ancestors' in response.headers['content-security-policy']


def test_expiry_and_restart_drop_grants_sessions(api_env):
    client, app, runs, paths, token=api_env
    code=app.state.auth.issue()
    app.state.auth.grants[code]=0
    assert app.state.auth.exchange(code) is None
    code=app.state.auth.issue()
    fresh=create_app(paths,'test',18765)
    assert fresh.state.auth.exchange(code) is None


def test_get_empty_no_business_writes_and_idempotent_runs(api_env):
    client,app,runs,paths,token=api_env
    before=db_hash(runs)
    for path in ['/', '/static/app.js','/v1/products','/v1/runs/latest','/v1/settings/default-plan','/v1/sites']:
        assert client.get(path).status_code==200
    assert client.get('/v1/runs/latest').json()['latest_run'] is None
    assert before==db_hash(runs)
    body={'request_key':'one-intent','trigger':'ui','overrides':{}}
    first=client.post('/v1/runs',json=body)
    assert first.status_code==202
    run=first.json()['run']; assert run['worker_state']=='offline' and run['state']=='queued'
    assert client.post('/v1/runs',json=body).json()['reuse_reason']=='request_key'
    assert client.get('/v1/runs/by-request/one-intent').json()['run']['id']==run['id']
    reused=client.post('/v1/runs',json={**body,'request_key':'other','overrides':{'window_days':7}}).json()
    assert reused['reuse_reason']=='active_run' and reused['ignored_overrides']==['window_days']
    assert client.post('/v1/runs',json={**body,'overrides':{'window_days':7}}).status_code==409
    assert client.post(f"/v1/runs/{run['id']}/cancel",json={'request_key':'cancel'}).json()['run']['state']=='cancelled'
    assert client.post('/v1/runs',json=body).json()['run']['state']=='cancelled'
    assert client.post(f"/v1/runs/{run['id']}/retry",json={'request_key':'retry','scope':'failed'}).json()['run']['id']==run['id']
    with runs.db.read() as conn:assert conn.execute('SELECT COUNT(*) FROM runs').fetchone()[0]==1


@pytest.mark.parametrize('body',[{'request_key':'x','trigger':'ui','surprise':1},{'request_key':2,'trigger':'ui'},{'request_key':'x','trigger':'ui','overrides':{'site_ids':'futario'}},{'request_key':'x','trigger':'ui','overrides':None}])
def test_strict_create(api_env,body):
    client,app,runs,paths,token=api_env
    assert client.post('/v1/runs',json=body).status_code==422


def test_partial_plan_cas_and_unsupported_no_side_effects(api_env):
    client,app,runs,paths,token=api_env
    before=client.get('/v1/settings/default-plan').json()
    response=client.patch('/v1/settings/default-plan',json={'expected_revision':1,'window_days':7})
    assert response.status_code==200 and response.json()['plan']['network']==before['plan']['network']
    assert client.patch('/v1/settings/default-plan',json={'expected_revision':1,'max_details':1}).status_code==409
    assert client.patch('/v1/settings/default-plan',json={'expected_revision':True,'max_details':1}).status_code==422
    assert client.patch('/v1/settings/default-plan',json={'expected_revision':2,'max_details':None}).status_code==422
    assert client.patch('/v1/settings/default-plan',json={'expected_revision':2,'window_days':7.0}).status_code==422
    assert client.post('/v1/runs',json={'request_key':'float-days','trigger':'ui','overrides':{'window_days':7.0}}).status_code==422
    assert client.post('/v1/session/bootstrap',json={'unexpected':True}).status_code==422
    before=db_hash(runs)
    for body in [{'request_key':'r','item_ids':['item']},{'request_key':'r','scope':'failed','item_ids':['item']}]:
        assert client.post('/v1/runs/unused/retry',json=body).status_code==501
    for ids in [None,[],[''],[1],['a','a']]:
        assert client.post('/v1/runs/unused/retry',json={'request_key':'r','item_ids':ids}).status_code==422
    assert client.post('/v1/exports',json={}).status_code==422
    for path in ['/v1/maintenance/verify']:
        assert client.post(path,json={}).status_code==422
    assert db_hash(runs)==before


def test_frozen_query_chain_mutations_replay_expiry_restart(api_env):
    client,app,runs,paths,token=api_env
    ids=seed(runs,paths,7)
    visible=[pid for i,pid in enumerate(ids) if i%4!=3]
    before=db_hash(runs)
    first=client.get('/v1/products?limit=2').json();assert [p['id'] for p in first['items']]==ids[:2]
    assert db_hash(runs)==before
    cursor=first['next_cursor']
    with runs.db.write() as conn:
        conn.execute("UPDATE product_user_state SET viewed_at='2026-10-06T12:00:00Z' WHERE product_id=?",(ids[0],))
        conn.execute("UPDATE product_user_state SET excluded=1,category_override='tops',favorite=1 WHERE product_id=?",(ids[2],))
    found=ids[:2]
    replay=client.get('/v1/products',params={'limit':2,'cursor':cursor}).json()
    assert [p['id'] for p in replay['items']]==visible[2:4]
    assert client.get('/v1/products',params={'limit':2,'cursor':cursor}).json()['items']==replay['items']
    assert client.get('/v1/products',params={'limit':2,'view':'favorites','cursor':cursor}).status_code==409
    while cursor:
        page=client.get('/v1/products',params={'limit':2,'cursor':cursor}).json();found += [p['id'] for p in page['items']];cursor=page['next_cursor']
    assert found==visible and len(set(found))==len(found)
    refreshed=client.get('/v1/products').json()['items'];assert refreshed[-1]['id']==ids[0] and ids[2] not in [p['id'] for p in refreshed]
    app.state.presentation.snapshots.entries.clear()
    assert client.get('/v1/products',params={'limit':2,'cursor':first['next_cursor']}).status_code==410
    fresh=TestClient(create_app(paths,'test',18765),base_url='http://127.0.0.1:18765',headers={'Authorization':'Bearer '+token})
    assert fresh.get('/v1/products',params={'limit':2,'cursor':first['next_cursor']}).status_code==410


def test_user_cas_null_missing_images_and_view_evidence(api_env):
    client,app,runs,paths,token=api_env
    ids=seed(runs,paths,4)
    response=client.patch('/v1/products/'+ids[3]+'/user-state',json={'expected_revision':1,'favorite':True})
    assert response.status_code==200
    assert client.get('/v1/products?view=favorites').json()['items'][0]['id']==ids[3]
    assert client.patch('/v1/products/'+ids[3]+'/user-state',json={'expected_revision':1,'excluded':True}).status_code==409
    for bad in [1,'true',None]:assert client.patch('/v1/products/'+ids[3]+'/user-state',json={'expected_revision':2,'favorite':bad}).status_code==422
    client.patch('/v1/products/'+ids[3]+'/user-state',json={'expected_revision':2,'category_override':'dress'})
    user=client.patch('/v1/products/'+ids[3]+'/user-state',json={'expected_revision':3,'category_override':None}).json()['user_state']
    assert user['favorite'] is True and user['category_override'] is None
    p=client.get('/v1/products/'+ids[0]).json()['product'];event={'event_id':'seen-1','version_id':p['version_id'],'version_revision':p['version_revision']}
    assert client.post('/v1/products/'+ids[0]+'/view-events',json={**event,'version_revision':999}).status_code==404
    viewed=client.post('/v1/products/'+ids[0]+'/view-events',json=event).json()
    assert viewed['user_state']['seen_content_digest']==digest({'sha256':sorted({x['sha256'] for x in p['images']})})
    with runs.db.write() as conn:conn.execute("UPDATE product_user_state SET seen_content_digest='newer-evidence',viewed_at='later' WHERE product_id=?",(ids[0],))
    replay=client.post('/v1/products/'+ids[0]+'/view-events',json=event).json();assert replay['reused'] and replay['user_state']['seen_content_digest']=='newer-evidence'
    assert client.post('/v1/products/'+ids[1]+'/view-events',json=event).status_code==409
    p=client.get('/v1/products/'+ids[3]).json()['product']
    assert client.post('/v1/products/'+ids[3]+'/view-events',json={'event_id':'missing','version_id':p['version_id'],'version_revision':1}).status_code==409


def test_assets_roots_readonly_and_traversal(api_env):
    client,app,runs,paths,token=api_env
    seed(runs,paths,1);before=db_hash(runs)
    assert client.get('/v1/assets/fixture-asset-0-0?rendition=preview').headers['content-type']=='image/jpeg'
    assert client.get('/v1/assets/fixture-asset-0-0?rendition=original').headers['content-type']=='image/png'
    assert client.get('/v1/assets/missing').status_code==404
    assert client.get('/v1/assets/..%2f..%2fcontrol%2ftest.key').status_code==404
    assert client.get('/v1/assets/fixture-asset-0-0?rendition=arbitrary').status_code==422
    assert db_hash(runs)==before
    with runs.db.write() as conn:conn.execute("UPDATE assets SET relative_path='../control/test.key' WHERE id='fixture-asset-0-0'")
    assert client.get('/v1/assets/fixture-asset-0-0').status_code==404
    (paths.media/'fixture-asset-0-1.png').unlink()
    assert client.get('/v1/assets/fixture-asset-0-1').status_code==404


def test_version_history_content_sets_and_failed_observation_fallback(api_env):
    client,app,runs,paths,token=api_env
    seed(runs,paths,1)
    pid='fixture-000'
    original=client.get('/v1/products/'+pid).json()['product']
    viewed=client.post('/v1/products/'+pid+'/view-events',json={'event_id':'original','version_id':original['version_id'],'version_revision':1})
    original_digest=viewed.json()['user_state']['seen_content_digest']
    with runs.db.write() as conn:
        manifest=json.loads(conn.execute('SELECT manifest_json FROM product_versions').fetchone()[0])
    def version(revision,images,available=True,complete=True,enumerated=True):
        changed={**manifest,'images':images,'complete':complete,'enumeration_complete':enumerated}
        content=digest({'sha256':sorted({r['sha256'] for r in images if r['sha256']})})
        with runs.db.write() as conn:
            conn.execute('INSERT INTO product_versions VALUES (?, ?, ?, ?, ?, ?)',(original['version_id'],revision,pid,digest(changed),canonical(changed),content))
            for image in images:conn.execute('INSERT INTO version_images VALUES (?,?,?,?,?,?)',(original['version_id'],revision,image['source_image_id'],image['url'],image['ordinal'],image['asset_id']))
            conn.execute('UPDATE products SET latest_observed_revision=? WHERE id=?',(revision,pid))
            if available:conn.execute('UPDATE products SET latest_available_revision=? WHERE id=?',(revision,pid))
    reordered=[{**image,'ordinal':1-i,'url':'https://example.invalid/changed-'+str(i)} for i,image in enumerate(manifest['images'])]
    version(2,list(reversed(reordered)))
    p=client.get('/v1/products/'+pid).json()['product']
    assert p['version_revision']==2 and not p['has_material_update']
    version(3,[reordered[0]])
    assert client.get('/v1/products/'+pid).json()['product']['has_material_update']
    historical=client.get('/v1/products/'+pid,params={'version_id':original['version_id'],'version_revision':1}).json()['product']
    assert historical['version_revision']==1 and len(historical['images'])==2
    client.post('/v1/products/'+pid+'/view-events',json={'event_id':'history','version_id':original['version_id'],'version_revision':1})
    assert app.state.presentation.user(pid)['seen_content_digest']==original_digest
    version(4,[{**r,'asset_id':None,'sha256':None,'error_code':'HTTP_404'} for r in manifest['images']],available=False,complete=False,enumerated=False)
    p=client.get('/v1/products/'+pid).json()['product']
    assert p['using_previous_images'] and p['version_revision']==3 and len(p['images'])==1
    assert p['latest_observed_revision']==4 and p['latest_observed_album']['stored_count']==0
    assert p['latest_observed_album']['expected_count'] is None and len(p['latest_observed_album']['missing'])==2
    assert p['media_state']=='failed'


def test_expired_clock_and_favorites_remain_in_current_chain(api_env):
    client,app,runs,paths,token=api_env
    seed(runs,paths,4)
    with runs.db.write() as conn:conn.execute('UPDATE product_user_state SET favorite=1')
    first=client.get('/v1/products?view=favorites&limit=2').json()
    with runs.db.write() as conn:conn.execute("UPDATE product_user_state SET favorite=0 WHERE product_id='fixture-002'")
    page=client.get('/v1/products',params={'view':'favorites','limit':2,'cursor':first['next_cursor']}).json()
    assert [p['id'] for p in page['items']]==['fixture-002','fixture-003']
    app.state.presentation.snapshots.clock=lambda:10**12
    assert client.get('/v1/products',params={'view':'favorites','limit':2,'cursor':first['next_cursor']}).status_code==410


def test_missing_local_file_is_not_material_update_and_keeps_version_digest(api_env):
    client,app,runs,paths,token=api_env
    seed(runs,paths,1)
    body={'event_id':'first','version_id':'fixture-version-0','version_revision':1}
    first=client.post('/v1/products/fixture-000/view-events',json=body).json()['user_state']
    (paths.media/'fixture-asset-0-1.png').unlink()
    p=client.get('/v1/products/fixture-000').json()['product']
    assert len(p['images'])==1 and not p['has_material_update'] and p['media_state']=='partial'
    later=client.post('/v1/products/fixture-000/view-events',json={**body,'event_id':'later'}).json()['user_state']
    assert first['seen_content_digest']==later['seen_content_digest']
