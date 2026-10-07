from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import uuid
from unittest.mock import patch
import pytest
from fashion_scout.config import Paths
from fashion_scout.db import Database
from fashion_scout.services.runs import Runs
from fashion_scout.processes import identity
from fashion_scout.exports.jobs import Jobs
from fashion_scout.exports.runner import ExportRunner,ExportInterrupted
from fashion_scout.exports import export_zip
from fashion_scout.domain import ScoutError
from tests.api.helpers import seed
from tests.api.conftest import api_env


@pytest.fixture
def setup(tmp_path):
    paths=Paths.at(tmp_path);paths.prepare();runs=Runs(Database(paths.db));runs.initialize()
    seed(runs,paths,count=4)
    with runs.db.write() as conn:conn.execute("UPDATE product_user_state SET favorite=1")
    return Jobs(paths),runs,paths


def owner(runs):
    who=identity();key=uuid.uuid4().hex
    runs.register_worker(key,who['pid'],who['born'],who['executable'])
    return key


def finish(jobs,runs):
    key=owner(runs);lease=jobs.claim(key)
    snap,roots,directory=jobs.work(lease)
    result=export_zip(snap,roots,directory)
    jobs.finish(lease,result)
    return lease,result


def test_concurrent_create_freeze_retry(setup):
    jobs,runs,paths=setup
    with ThreadPoolExecutor(max_workers=4) as pool:accepted=list(pool.map(lambda _:jobs.create('same'),range(4)))
    assert len({x[0] for x in accepted})==1 and sum(not x[1] for x in accepted)==1
    jid=accepted[0][0]
    with runs.db.write() as conn:
        frozen=conn.execute('SELECT snapshot_json FROM export_jobs WHERE id=?',(jid,)).fetchone()[0]
        conn.execute('UPDATE product_user_state SET favorite=0,category_override=\'tops\'')
        conn.execute('UPDATE products SET latest_observed_version_id=NULL,latest_observed_revision=NULL')
    lease,result=finish(jobs,runs)
    assert result.state=='partial' and result.missing_count==2
    assert jobs.get(jid)['counts']['products']==4
    stream,size=jobs.download(jid);assert len(stream.read())==size;stream.close()
    assert jobs.retry(jid,'retry-key') is False and jobs.retry(jid,'retry-key') is True
    with pytest.raises(ScoutError) as e:jobs.create('retry-key')
    assert e.value.code=='REQUEST_KEY_CONFLICT'
    with jobs.db.read() as conn:
        row=jobs.row(conn,jid);assert row['snapshot_json']==frozen and row['attempt']==2
        assert conn.execute('SELECT COUNT(*) FROM runs').fetchone()[0]==1
    finish(jobs,runs)
    assert jobs.get(jid)['attempt']==2


def test_live_owner_not_stolen_and_old_epoch_cannot_finish(setup):
    jobs,runs,paths=setup;jid,_=jobs.create('one');key=owner(runs);lease=jobs.claim(key,1)
    jobs.recover(lambda _:False)
    assert jobs.get(jid)['state']=='running'
    with jobs.db.write() as conn:conn.execute('UPDATE export_jobs SET lease_until=0')
    jobs.recover(lambda _:False)
    assert jobs.get(jid)['state']=='running'
    snap,roots,directory=jobs.work(lease);result=export_zip(snap,roots,directory)
    jobs.recover(lambda _:True)
    with pytest.raises(ScoutError) as e:jobs.finish(lease,result)
    assert e.value.code=='STALE_EXPORT_LEASE'
    next_lease=jobs.claim(owner(runs));assert next_lease.epoch>lease.epoch and next_lease.attempt==lease.attempt
    snap,roots,directory=jobs.work(next_lease);reused=export_zip(snap,roots,directory)
    assert reused.reused
    jobs.finish(next_lease,reused)


def test_capture_keeps_history_while_latest_observed_is_missing(setup):
    jobs,runs,paths=setup
    with jobs.db.write() as conn:
        old=conn.execute("SELECT * FROM product_versions WHERE id='fixture-version-0'").fetchone()
        manifest=json.loads(old['manifest_json'])
        manifest['images']=[{'source_image_id':'latest-missing','url':'https://example.invalid/missing.png','ordinal':0,'asset_id':None,'error_code':'HTTP_404'}]
        manifest.update(expected_count=1,complete=False)
        conn.execute('INSERT INTO product_versions VALUES (?,2,?,?,?,?)',('fixture-version-0','fixture-000','new-manifest',json.dumps(manifest),old['content_digest']))
        conn.execute("INSERT INTO version_images VALUES ('fixture-version-0',2,'latest-missing','https://example.invalid/missing.png',0,NULL)")
        conn.execute("UPDATE products SET latest_observed_revision=2 WHERE id='fixture-000'")
    jid,_=jobs.create('history')
    with jobs.db.read() as conn:snapshot=jobs.snapshot(jobs.row(conn,jid))
    product=next(p for p in snapshot.products if p.product_id=='fixture-000')
    assert [v.revision for v in product.versions]==[1,2]
    assert product.latest_available.revision==1 and product.latest_observed.revision==2
    assert {a.asset_id for a in snapshot.assets}>={'fixture-asset-0-0','fixture-asset-0-1'}
    lease,result=finish(jobs,runs)
    assert result.state=='partial' and result.missing_count==3


def test_published_before_db_failure_reuses_same_attempt(setup):
    jobs,runs,paths=setup;jid,_=jobs.create('publish-fault');key=owner(runs)
    runner=ExportRunner(paths,key,lambda:False,lambda:None)
    lease=jobs.claim(key)
    with patch.object(runner.jobs,'finish',side_effect=OSError('synthetic DB failure')):
        with pytest.raises(OSError):runner.execute(lease)
    assert len(list((paths.root/'exports').rglob('*.zip')))==1
    jobs.release(lease);new=jobs.claim(key);runner.execute(new)
    with jobs.db.read() as conn:
        row=jobs.row(conn,jid);assert json.loads(row['result_json'])['reused'] and row['attempt']==1


def test_stop_checkpoint_leaves_same_job_queued(setup):
    jobs,runs,paths=setup;jid,_=jobs.create('stop');key=owner(runs);lease=jobs.claim(key)
    ExportRunner(paths,key,lambda:True,lambda:None).execute(lease)
    assert jobs.get(jid)['state']=='queued' and jobs.get(jid)['attempt']==1


def test_download_missing_tampered_unready_and_path_control(setup):
    jobs,runs,paths=setup;jid,_=jobs.create('download')
    with pytest.raises(ScoutError) as e:jobs.download(jid)
    assert e.value.status==409
    lease,result=finish(jobs,runs)
    Path(result.path).write_bytes(b'not a zip')
    assert jobs.get(jid)['download_url'] is None and 'EXPORT_UNAVAILABLE' in jobs.get(jid)['issues']
    with pytest.raises(ScoutError) as e:jobs.download(jid)
    assert e.value.status==410
    Path(result.path).unlink()
    with pytest.raises(ScoutError) as e:jobs.download(jid)
    assert e.value.status==410
    with pytest.raises(ScoutError):jobs.directory('../../escape',1)


def test_export_api_auth_strict_empty_replay_and_download(api_env):
    client,app,runs,paths,token=api_env
    assert client.post('/v1/exports',json={}).status_code==422
    assert client.post('/v1/exports',json={'request_key':'empty','selection':'favorites'}).status_code==422
    seed(runs,paths,count=1)
    with runs.db.write() as conn:conn.execute('UPDATE product_user_state SET favorite=1')
    body={'request_key':'api','selection':'favorites'}
    assert client.post('/v1/exports',json={**body,'url':'https://evil.invalid'}).status_code==422
    assert client.post('/v1/exports',json=body,headers={'Authorization':'','Origin':'https://evil.invalid'}).status_code==403
    assert client.post('/v1/exports',json=body,headers={'Authorization':''}).status_code==401
    response=client.post('/v1/exports',json=body);assert response.status_code==202
    jid=response.json()['export']['id']
    assert client.post('/v1/exports',json=body).json()['reused']
    assert client.get(f'/v1/exports/{jid}/download').status_code==409
    finish(Jobs(paths),runs)
    status=client.get(f'/v1/exports/{jid}').json()['export'];assert status['download_url']
    download=client.get(status['download_url']);assert download.status_code==200 and download.content[:2]==b'PK'
    assert client.get(status['download_url'],headers={'Authorization':''}).status_code==401
    assert client.post('/v1/maintenance/backup',json={}).status_code==422
    with runs.db.read() as conn:assert conn.execute('SELECT COUNT(*) FROM export_jobs').fetchone()[0]==1


def test_existing_schema7_upgrade_preserves_rows(tmp_path):
    import hashlib,sqlite3
    from fashion_scout.db import store
    path=tmp_path/'old.sqlite3';conn=sqlite3.connect(path)
    conn.execute('CREATE TABLE schema_migrations(version INTEGER PRIMARY KEY,sha256 TEXT NOT NULL)')
    directory=Path(store.__file__).parent/'migrations'
    for p in sorted(directory.glob('*.sql')):
        version=int(p.name.split('_')[0])
        if version>=8:continue
        sql=p.read_text('utf-8');conn.executescript(sql)
        conn.execute('INSERT INTO schema_migrations VALUES (?,?)',(version,hashlib.sha256(sql.encode()).hexdigest()));conn.commit()
    conn.execute("INSERT INTO sites(id,entry,adapter_version,enabled) VALUES ('fixture','https://example.invalid','fixture',1)")
    conn.execute("INSERT INTO products(id,site_id,source_id,first_seen_at) VALUES ('retained','fixture','1','2026-10-06')")
    conn.execute("INSERT INTO product_user_state(product_id,favorite,revision) VALUES ('retained',1,7)")
    conn.commit();conn.close();db=Database(path);db.initialize()
    with db.read() as conn:
        assert conn.execute('SELECT MAX(version) FROM schema_migrations').fetchone()[0]==10
        assert conn.execute('SELECT COUNT(*) FROM export_attempts').fetchone()[0]==0
        assert conn.execute("SELECT favorite,revision FROM product_user_state WHERE product_id='retained'").fetchone()[:]==(1,7)
