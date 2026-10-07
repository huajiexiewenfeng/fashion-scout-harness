import hashlib
import io
import json
import zipfile
from fashion_scout.exports.models import ExportSnapshot,capture_snapshot,load_snapshot
from tests.t2_helpers import Scenario,product,execute
from .conftest import worker,eventually
from .test_bridge import PRODUCT,accepted,listing,detail,tickets,upload,finish,key,ok


def test_frozen_v1_replay_and_mixed_history_keep_all_unique_sha(env):
    client,runs,paths,app=env
    current=ok(client.get('/v1/settings/default-plan'))
    ok(client.patch('/v1/settings/default-plan',json={'expected_revision':current['revision'],
         'network':{**current['plan']['network'],'min_interval_ms':1}}))
    old=ok(client.post('/v1/runs',json={'request_key':key(),'trigger':'skill','overrides':{}}))['run']
    item=product(PRODUCT['source_id']);item['handle']=PRODUCT['handle']
    execute(runs,paths,old['id'],Scenario([item]))
    pid='futario-'+PRODUCT['source_id']
    before=ok(client.get('/v1/products/'+pid))['product']
    complete_pointer=(before['latest_complete_version_id'],before['latest_complete_revision'])
    ok(client.patch('/v1/products/'+pid+'/user-state',json={'expected_revision':before['user_state']['revision'],'favorite':True}))
    original_key=key();old_job=ok(client.post('/v1/exports',json={'request_key':original_key,'selection':'favorites'}))['export']['id']
    with runs.db.read() as conn:
        row=conn.execute('SELECT * FROM export_jobs WHERE id=?',(old_job,)).fetchone()
        original_json,original_hash=row['snapshot_json'],row['snapshot_hash']
        snapshot=ExportSnapshot.model_validate_json(original_json)
        assert snapshot.schema_version==1 and load_snapshot(original_json).digest==original_hash
        old_sha={a.sha256 for a in snapshot.assets}
    with worker(paths):
        eventually(lambda:ok(client.get('/v1/exports/'+old_job))['export']['state']=='succeeded')
        old_zip=client.get('/v1/exports/'+old_job+'/download').content
        rid,prefix,sid=accepted(client)
        listing(client,prefix,sid);detail(client,prefix,sid,2)
        for ticket in tickets(client,prefix,2):ok(upload(client,prefix,sid,ticket))
        finish(client,prefix,sid);eventually(lambda:runs.get(rid).state=='partial')
        after=ok(client.get('/v1/products/'+pid))['product']
        assert (after['latest_complete_version_id'],after['latest_complete_revision'])==complete_pointer
        replay=ok(client.post('/v1/exports',json={'request_key':original_key,'selection':'favorites'}))
        assert replay['export']['id']==old_job
        assert client.get('/v1/exports/'+old_job+'/download').content==old_zip
        with runs.db.read() as conn:
            row=conn.execute('SELECT * FROM export_jobs WHERE id=?',(old_job,)).fetchone()
            assert (row['snapshot_json'],row['snapshot_hash'])==(original_json,original_hash)
        new_job=ok(client.post('/v1/exports',json={'request_key':key(),'selection':'favorites'}))['export']['id']
        eventually(lambda:ok(client.get('/v1/exports/'+new_job))['export']['state']=='partial')
        blob=client.get('/v1/exports/'+new_job+'/download').content
        with zipfile.ZipFile(io.BytesIO(blob)) as package:
            manifest=json.loads(package.read('manifest.json'))
            assert manifest['schema_version']==2 and manifest['unknown_count']>=1
            versions=manifest['snapshot']['products'][0]['versions']
            assert {v['coverage_scope'] for v in versions}=={'product.images','browser.gallery'}
            packed_sha={hashlib.sha256(package.read(name)).hexdigest() for name in package.namelist() if '/images/' in name}
            frozen_sha={a['sha256'] for a in manifest['snapshot']['assets']}
            assert len(packed_sha)==3 and packed_sha==frozen_sha and old_sha<=packed_sha
            assert capture_snapshot(manifest['snapshot']).digest==manifest['snapshot_sha256']
        # Explicit retry reuses the exact old v1 snapshot and deterministic bytes.
        ok(client.post('/v1/exports/'+old_job+'/retry',json={'request_key':key()}))
        eventually(lambda:ok(client.get('/v1/exports/'+old_job))['export']['state']=='succeeded')
        assert client.get('/v1/exports/'+old_job+'/download').content==old_zip
