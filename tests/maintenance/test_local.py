from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import sqlite3
import uuid
from unittest.mock import patch
import pytest
from fashion_scout.config import Paths
from fashion_scout.db import Database
from fashion_scout.db.archive import Archive
from fashion_scout.domain import CreateRun,ScoutError,Outcome
from fashion_scout.services.runs import Runs
from fashion_scout.processes import identity
from fashion_scout.maintenance.jobs import Jobs
from fashion_scout.maintenance.runner import MaintenanceRunner
from fashion_scout.maintenance.backup import backup,verify_bundle
from fashion_scout.maintenance.files import MaintenanceError
from fashion_scout.maintenance.restore import restore
from fashion_scout.maintenance.storage import Storage
from tests.api.helpers import seed
from tests.api.conftest import api_env


@pytest.fixture
def setup(tmp_path):
    paths=Paths.at(tmp_path/'original');paths.prepare();runs=Runs(Database(paths.db));runs.initialize();seed(runs,paths,count=4)
    who=identity();owner=uuid.uuid4().hex;runs.register_worker(owner,who['pid'],who['born'],who['executable'])
    return paths,runs,Jobs(paths),owner


def execute(paths,jobs,owner):
    lease=jobs.claim(owner);MaintenanceRunner(paths,owner,lambda:False,lambda:None).execute(lease)
    return jobs.get(lease.job_id)


def test_verify_idempotent_frozen_no_user_changes_and_dedup(setup):
    paths,runs,jobs,owner=setup
    with runs.db.read() as conn:before=[tuple(r) for r in conn.execute('SELECT * FROM product_user_state')]
    with ThreadPoolExecutor(max_workers=4) as pool:rows=list(pool.map(lambda _:jobs.create('verify','same',{'scope':'all'}),range(4)))
    assert len({r[0] for r in rows})==1 and sum(not r[1] for r in rows)==1
    with pytest.raises(ScoutError):jobs.create('backup','same',{'destination_id':'local'})
    result=execute(paths,jobs,owner);assert result['state']=='partial' and result['result']['counts']['missing']==2
    jobs.create('verify','again',{'scope':'all'});execute(paths,jobs,owner)
    with runs.db.read() as conn:
        assert [tuple(r) for r in conn.execute('SELECT * FROM product_user_state')]==before
        assert conn.execute('SELECT COUNT(*) FROM maintenance_findings').fetchone()[0]==2
        assert conn.execute('SELECT COUNT(*) FROM collection_http').fetchone()[0]==0
    with pytest.raises(ScoutError):jobs.create('verify','empty',{'scope':'selected','product_ids':[]})


def test_verify_missing_damaged_unknown_and_fence(setup):
    paths,runs,jobs,owner=setup
    jobs.create('verify','damage',{'scope':'all'});lease=jobs.claim(owner)
    (paths.media/'fixture-asset-0-0.png').unlink()
    (paths.media/'fixture-asset-0-1.png').write_bytes(b'broken')
    jobs.recover(lambda _:False);assert jobs.get(lease.job_id)['state']=='running'
    jobs.recover(lambda _:True)
    with pytest.raises(ScoutError):jobs.finish(lease,{'state':'succeeded'})
    result=execute(paths,jobs,owner)
    assert result['result']['counts']['missing']==3 and result['result']['counts']['damaged']==1


def test_backup_partial_restore_guard_and_original_unchanged(setup,tmp_path):
    paths,runs,jobs,owner=setup;jid,_=jobs.create('backup','backup',{'destination_id':'local'})
    result=execute(paths,jobs,owner);assert result['state']=='partial' and result['backup_available']
    bundle=Path(result['result']['path']);manifest,digest=verify_bundle(bundle)
    original_hash=hashlib.sha256((bundle/'database.sqlite3').read_bytes()).hexdigest()
    with pytest.raises(ScoutError) as e:restore(paths.root,jid,tmp_path/'restored')
    assert e.value.code=='PARTIAL_BACKUP' and not (tmp_path/'restored').exists()
    out=restore(paths.root,jid,tmp_path/'restored',True);assert out['state']=='partial' and not out['services_started']
    assert hashlib.sha256((bundle/'database.sqlite3').read_bytes()).hexdigest()==original_hash
    with pytest.raises(ScoutError):restore(paths.root,jid,tmp_path/'restored',True)
    with Database(tmp_path/'restored/scout.sqlite3').read() as conn:
        assert conn.execute('SELECT COUNT(*) FROM products').fetchone()[0]==4
        assert conn.execute("SELECT COUNT(*) FROM workers WHERE state='online'").fetchone()[0]==0
        assert conn.execute("SELECT COUNT(*) FROM maintenance_jobs WHERE state IN ('queued','running')").fetchone()[0]==0
        assert conn.execute('SELECT COUNT(*) FROM restore_audit').fetchone()[0]==1
    p=bundle/next(f['path'] for f in manifest['files'] if f['path'].startswith('assets/'));p.write_bytes(b'tampered')
    with pytest.raises(MaintenanceError):restore(paths.root,jid,tmp_path/'bad',True)
    assert jobs.get(jid)['backup_available'] is False


def test_backup_published_reuse_and_disk_failure(setup):
    paths,runs,jobs,owner=setup;jid,_=jobs.create('backup','once',{'destination_id':'local'})
    lease=jobs.claim(owner);one=backup(paths,jid);two=backup(paths,jid)
    assert not one['reused'] and two['reused'] and one['manifest_sha256']==two['manifest_sha256']
    jobs.finish(lease,two)
    second,_=jobs.create('backup','disk',{'destination_id':'local'})
    with patch('fashion_scout.maintenance.backup.shutil.disk_usage',return_value=type('Space',(),{'free':0})()):
        result=execute(paths,jobs,owner)
    assert result['state']=='failed' and result['issue_code']=='DISK_RESERVE'
    assert not (paths.root/'backups'/second).exists()


def test_storage_single_authority_refresh_and_archive(setup,tmp_path):
    paths,runs,jobs,owner=setup
    (paths.root/'app.json').write_text(json.dumps({'media_root':str(paths.media)}))
    storage=Storage(paths);assert storage.get()['revision']==0
    new=tmp_path/'new-media';storage.patch(0,str(new))
    (paths.root/'app.json').write_text(json.dumps({'media_root':str(tmp_path/'stale')}))
    assert Paths.at(paths.root).media==new and paths.media==new
    assert (paths.root/'media/fixture-asset-0-0.png').exists()
    with pytest.raises(ScoutError):storage.patch(0,str(tmp_path/'other'))
    run=runs.create(CreateRun(request_key='archive',trigger='skill')).run;lease=runs.claim(owner)
    with pytest.raises(ScoutError) as e:storage.patch(1,str(tmp_path/'other'))
    assert e.value.code=='STORAGE_BUSY'
    archive=Archive(paths.for_run(lease.run_id),runs)
    item=runs.ensure_item(lease,'new');runs.start_item(lease,item)
    relative=archive.create_temp(lease,item);p=paths.inside_media(relative);p.write_bytes(b'new file')
    jid=archive.stage(lease,item,relative,'originals/new.bin',hashlib.sha256(b'new file').hexdigest(),8)
    archive.commit(lease,jid);assert (new/'originals/new.bin').exists()


@pytest.mark.parametrize('value',[r'\\server\share\images',r'\\?\C:\media','C:/',r'C:\a\..\b'])
def test_storage_bad_paths(setup,value):
    paths,runs,jobs,owner=setup
    with pytest.raises(ScoutError):Storage(paths).patch(0,value)


def test_api_strict_auth_and_storage(api_env):
    client,app,runs,paths,token=api_env
    assert client.post('/v1/maintenance/verify',json={'request_key':'empty','scope':'selected','product_ids':[]}).status_code==422
    assert client.post('/v1/maintenance/verify',json={'request_key':'x','scope':'all','product_ids':[]}).status_code==422
    assert client.post('/v1/maintenance/backup',json={'request_key':'x','destination_id':'local','path':'C:/evil'}).status_code==422
    assert client.get('/v1/settings/storage',headers={'Authorization':''}).status_code==401
    body={'request_key':'verify','scope':'all'}
    assert client.post('/v1/maintenance/verify',json=body,headers={'Origin':'https://evil.invalid'}).status_code==403
    assert client.post('/v1/maintenance/verify',json=body).status_code==202
    assert client.post('/v1/maintenance/verify',json=body).json()['reused']
