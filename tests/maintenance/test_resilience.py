import hashlib
import json
from pathlib import Path
import secrets
import sqlite3
import subprocess
import threading
import time
from unittest.mock import patch
import pytest
from fastapi.testclient import TestClient
from fashion_scout.config import Paths
from fashion_scout.db import Database
from fashion_scout.db.archive import Archive
from fashion_scout.domain import CreateRun,Outcome,ScoutError
from fashion_scout.health import create_app
from fashion_scout.services.runs import Runs
from fashion_scout.worker import Worker
from fashion_scout.maintenance.backup import backup,verify_bundle
from fashion_scout.maintenance.restore import restore
from fashion_scout.maintenance.storage import Storage
from fashion_scout.maintenance.files import check_asset
from fashion_scout.exports.jobs import Jobs as ExportJobs
from fashion_scout.exports import export_zip
from tests.api.helpers import seed
from tests.api.conftest import api_env
from tests.maintenance.test_local import setup,execute


def wait(check,seconds=8):
    end=time.monotonic()+seconds
    while time.monotonic()<end:
        result=check()
        if result:return result
        time.sleep(.03)
    raise AssertionError('Expected local state not reached')


def test_restore_browses_cross_root_history_and_exports_without_original(setup,tmp_path):
    paths,runs,jobs,owner=setup
    extra=paths.root/'second-media';extra.mkdir()
    original=paths.media/'fixture-asset-0-0.png';(extra/original.name).write_bytes(original.read_bytes())
    with runs.db.write() as conn:
        conn.execute("INSERT INTO storage_roots VALUES ('second',?,'media')",(str(extra),))
        conn.execute("UPDATE assets SET root_id='second' WHERE id='fixture-asset-0-0'")
        conn.execute("UPDATE product_user_state SET favorite=1,category_override='tops',viewed_at='earlier',revision=7")
        conn.execute("INSERT INTO network_throttle VALUES ('futario',NULL,'unknown',NULL,123)")
        row=conn.execute("SELECT * FROM product_versions WHERE id='fixture-version-0'").fetchone()
        conn.execute('INSERT INTO product_versions VALUES (?,2,?,?,?,?)',(row['id'],row['product_id'],row['manifest_digest'],row['manifest_json'],row['content_digest']))
        conn.execute("INSERT INTO version_images SELECT version_id,2,source_image_id,source_url,ordinal,asset_id FROM version_images WHERE version_id='fixture-version-0' AND revision=1")
    held=runs.create(CreateRun(request_key='held',trigger='skill')).run.id
    old_export,_=ExportJobs(paths).create('old-export')
    jid,_=jobs.create('backup','restore',{'destination_id':'local'});result=execute(paths,jobs,owner)
    assert result['state']=='partial'
    with runs.db.read() as conn:
        source_dump=list(conn.iterdump());users=[tuple(r) for r in conn.execute('SELECT * FROM product_user_state ORDER BY product_id')]
    package_hashes={str(p.relative_to(paths.root/'backups'/jid)):hashlib.sha256(p.read_bytes()).hexdigest() for p in (paths.root/'backups'/jid).rglob('*') if p.is_file()}
    target=tmp_path/'restored';restored=restore(paths.root,jid,target,True)
    with runs.db.read() as conn:assert list(conn.iterdump())==source_dump
    # Only these two synthetic fixture media folders become unavailable.
    for old in (paths.root/'media',extra):
        new=old.with_name(old.name+'-offline')
        assert old.resolve().is_relative_to(paths.root) and new.resolve().is_relative_to(paths.root)
        old.rename(new)
    new_paths=Paths.at(target);new_paths.prepare();db=Database(new_paths.db)
    with db.read() as conn:
        assert [tuple(r) for r in conn.execute('SELECT * FROM product_user_state ORDER BY product_id')]==users
        assert conn.execute('SELECT state,issue_code FROM runs WHERE id=?',(held,)).fetchone()[:]==('cancelled','RESTORED_HELD')
        assert conn.execute('SELECT mode,not_before FROM network_throttle').fetchone()[:]==('unknown',None)
        assert conn.execute('SELECT COUNT(*) FROM runs').fetchone()[0]==2
        expected={r['id']:r['sha256'] for r in conn.execute('SELECT * FROM assets')}
    token=secrets.token_hex(32);(target/'control/test.key').write_text(token)
    with TestClient(create_app(new_paths,'test',18765),base_url='http://127.0.0.1:18765',headers={'Authorization':'Bearer '+token}) as client:
        assert client.get('/v1/products?view=favorites').json()['total']==4
        image=client.get('/v1/assets/fixture-asset-0-0?rendition=original')
        assert image.status_code==200 and hashlib.sha256(image.content).hexdigest()==expected['fixture-asset-0-0']
        assert client.get('/v1/products/fixture-000').json()['product']['versions']
    exports=ExportJobs(new_paths);assert exports.get(old_export)['download_url'] is None
    jid2,_=exports.create('new-export')
    new_runs=Runs(db);from fashion_scout.processes import identity
    who=identity();new_runs.register_worker('restored-owner',who['pid'],who['born'],who['executable'])
    lease=exports.claim('restored-owner');snap,roots,directory=exports.work(lease)
    output=export_zip(snap,roots,directory);exports.finish(lease,output)
    assert output.state=='partial' and output.missing_count==2
    assert len(snap.products[0].versions)==2
    # Existing restored root paths are reused without UNIQUE(path) collisions.
    archive=Archive(new_paths,new_runs);assert archive.paths.media==new_paths.media
    assert package_hashes=={str(p.relative_to(paths.root/'backups'/jid)):hashlib.sha256(p.read_bytes()).hexdigest() for p in (paths.root/'backups'/jid).rglob('*') if p.is_file()}


def test_live_writes_during_sqlite_backup_are_consistent(setup):
    paths,runs,jobs,owner=setup
    with runs.db.write() as conn:
        conn.execute('UPDATE settings SET revision=100');conn.execute('UPDATE product_user_state SET revision=100')
    stop=threading.Event();writes=[]
    def writer():
        number=101
        while not stop.is_set():
            with runs.db.write() as conn:
                conn.execute('UPDATE settings SET revision=?',(number,));conn.execute('UPDATE product_user_state SET revision=?',(number,))
            writes.append(number);number+=1;time.sleep(.005)
    thread=threading.Thread(target=writer);thread.start()
    try:
        jid,_=jobs.create('backup','concurrent',{'destination_id':'local'});lease=jobs.claim(owner)
        result=backup(paths,jid);jobs.finish(lease,result)
    finally:stop.set();thread.join()
    assert writes
    conn=sqlite3.connect(Path(result['path'])/'database.sqlite3')
    try:
        revision=conn.execute('SELECT revision FROM settings').fetchone()[0]
        assert {r[0] for r in conn.execute('SELECT revision FROM product_user_state')}=={revision}
    finally:conn.close()


def test_source_change_and_output_permission_are_not_success(setup):
    paths,runs,jobs,owner=setup
    with runs.db.read() as conn:asset=dict(conn.execute('SELECT * FROM assets LIMIT 1').fetchone())
    path=paths.media/asset['relative_path'];calls=[]
    def mutate():
        calls.append(1)
        if len(calls)==2:path.write_bytes(b'z'*asset['bytes'])
    assert check_asset(asset,{'fixture-root':str(paths.media)},checkpoint=mutate)['code']=='SOURCE_CHANGED'
    jobs.create('backup','permission',{'destination_id':'local'})
    original=Path.open
    def blocked(p,*args,**kwargs):
        if p.parent.name=='assets' and args and args[0]=='xb':raise PermissionError('test output')
        return original(p,*args,**kwargs)
    with patch.object(Path,'open',blocked):result=execute(paths,jobs,owner)
    assert result['state']=='failed' and result['issue_code']=='OUTPUT_WRITE_FAILED'


def test_long_lived_worker_refresh_and_old_run_retry(tmp_path):
    paths=Paths.at(tmp_path/'root');paths.prepare();runs=Runs(Database(paths.db));runs.initialize()
    stopped=threading.Event();locations=[]
    def executor(ctx):
        attempt=runs.get(ctx.lease.run_id).attempt
        archive=Archive(ctx.paths,runs);locations.append((ctx.lease.run_id,attempt,archive.paths.media))
        item=runs.ensure_item(ctx.lease,'item-'+str(attempt));runs.start_item(ctx.lease,item)
        relative=archive.create_temp(ctx.lease,item);data=b'synthetic'
        archive.paths.inside_media(relative).write_bytes(data)
        journal=archive.stage(ctx.lease,item,relative,'originals/'+ctx.lease.run_id+'-'+str(attempt),hashlib.sha256(data).hexdigest(),len(data))
        archive.commit(ctx.lease,journal)
        return Outcome(state='partial',valid_results=1,coverage_complete=False,required_complete=True,evidence_ref='synthetic')
    worker=Worker(paths,stopped.is_set,executor=executor);thread=threading.Thread(target=worker.run);thread.start()
    try:
        first=runs.create(CreateRun(request_key='first',trigger='skill')).run.id;wait(lambda:runs.get(first).state=='partial')
        old=locations[0][2];storage=Storage(paths);new=tmp_path/'new'
        storage.patch(storage.get()['revision'],str(new))
        second=runs.create(CreateRun(request_key='second',trigger='skill')).run.id;wait(lambda:runs.get(second).state=='partial')
        runs.retry(first,'old-retry');wait(lambda:runs.get(first).state=='partial' and len(locations)==3)
        assert [r[2] for r in locations]==[old,new,old]
        with runs.db.read() as conn:assert conn.execute('SELECT COUNT(*) FROM workers').fetchone()[0]==1
        assert Paths.at(paths.root).media==new
    finally:stopped.set();thread.join(timeout=8);assert not thread.is_alive()


def test_8_to_9_and_legacy_app_json_import(tmp_path):
    from fashion_scout.db import store
    root=tmp_path/'old';root.mkdir();dbfile=root/'scout.sqlite3';conn=sqlite3.connect(dbfile)
    conn.execute('CREATE TABLE schema_migrations(version INTEGER PRIMARY KEY,sha256 TEXT NOT NULL)')
    migrations=Path(store.__file__).parent/'migrations'
    for p in sorted(migrations.glob('*.sql')):
        version=int(p.name.split('_')[0])
        if version>8:continue
        sql=p.read_text('utf-8');conn.executescript(sql);conn.execute('INSERT INTO schema_migrations VALUES (?,?)',(version,hashlib.sha256(sql.encode()).hexdigest()));conn.commit()
    before=conn.execute('SELECT * FROM schema_migrations').fetchall();conn.close()
    legacy=tmp_path/'legacy-media';(root/'app.json').write_text(json.dumps({'media_root':str(legacy)}))
    paths=Paths.at(root);paths.prepare();runs=Runs(Database(dbfile));runs.initialize();Archive(paths,runs)
    assert Storage(paths).get()['media_root']==str(legacy)
    (root/'app.json').write_text('{bad json ignored after import')
    assert Paths.at(root).media==legacy
    with runs.db.read() as conn:
        assert [tuple(r) for r in conn.execute('SELECT * FROM schema_migrations WHERE version<=8')]==before
        assert conn.execute('SELECT MAX(version) FROM schema_migrations').fetchone()[0]==10


def test_real_junction_is_rejected(setup,tmp_path):
    paths,runs,jobs,owner=setup;target=tmp_path/'real';target.mkdir();link=tmp_path/'junction'
    subprocess.run(['cmd','/c','mklink','/J',str(link),str(target)],check=True,capture_output=True)
    try:
        with pytest.raises(ScoutError):Storage(paths).patch(0,str(link/'images'))
    finally:link.rmdir()


def test_unknown_enumeration_resolution_preserves_history(setup):
    paths,runs,jobs,owner=setup
    with runs.db.write() as c:
        row=c.execute("SELECT manifest_json FROM product_versions WHERE id='fixture-version-0'").fetchone()
        old=row[0];manifest=json.loads(old);manifest.update(enumeration_complete=False,expected_count=None)
        c.execute("UPDATE product_versions SET manifest_json=? WHERE id='fixture-version-0'",(json.dumps(manifest),))
    first,_=jobs.create('verify','unknown',{'scope':'selected','product_ids':['fixture-000']})
    one=execute(paths,jobs,owner);assert one['result']['counts']['unknown']==1
    with runs.db.write() as c:c.execute("UPDATE product_versions SET manifest_json=? WHERE id='fixture-version-0'",(old,))
    second,_=jobs.create('verify','resolved',{'scope':'selected','product_ids':['fixture-000']})
    two=execute(paths,jobs,owner);assert two['state']=='succeeded'
    with runs.db.read() as c:
        assert c.execute("SELECT resolved,last_job_id FROM maintenance_findings WHERE code='ENUMERATION_UNKNOWN'").fetchone()[:]==(1,second)
    assert jobs.get(first)['result']['counts']['unknown']==1


def test_published_before_completion_db_error_reuses(setup):
    from fashion_scout.maintenance.runner import MaintenanceRunner
    paths,runs,jobs,owner=setup;jid,_=jobs.create('backup','db-error',{'destination_id':'local'});lease=jobs.claim(owner)
    runner=MaintenanceRunner(paths,owner,lambda:False,lambda:None)
    with patch.object(runner.jobs,'finish',side_effect=OSError('synthetic database write failure')):
        with pytest.raises(OSError):runner.execute(lease)
    jobs.release(lease);result=execute(paths,jobs,owner)
    assert result['result']['reused'] and result['backup_available']


def test_restore_json_input_is_strict_and_offline(setup,tmp_path):
    import sys
    paths,runs,jobs,owner=setup;jid,_=jobs.create('backup','json-restore',{'destination_id':'local'});execute(paths,jobs,owner)
    target=tmp_path/'json-restored';input_file=tmp_path/'restore.json'
    payload={'backup_id':jid,'target':str(target),'allow_partial':True}
    command=[sys.executable,'-m','fashion_scout.maintenance.restore','--data-root',str(paths.root),'--json-input',str(input_file)]
    for bad in (json.dumps({**payload,'unknown':True}),json.dumps(payload)[:-1]+',"allow_partial":true}',json.dumps({**payload,'allow_partial':'yes'})):
        input_file.write_text(bad,'utf-8');result=subprocess.run(command,capture_output=True,text=True)
        assert result.returncode==1 and not target.exists()
    input_file.write_text(json.dumps(payload),'utf-8');result=subprocess.run(command,capture_output=True,text=True)
    assert result.returncode==0 and json.loads(result.stdout)['services_started'] is False
    assert not (target/'control').exists()


def test_maintenance_browser_csrf_guard(api_env):
    client,app,runs,paths,token=api_env
    with TestClient(app,base_url='http://127.0.0.1:18765') as browser:
        code=client.post('/v1/session/bootstrap',json={}).json()['bootstrap_url'].split('#')[1]
        origin={'Origin':'http://127.0.0.1:18765'}
        assert browser.post('/v1/session/exchange',headers=origin,json={'code':code}).status_code==200
        csrf=browser.get('/v1/session').json()['csrf_token']
        for path,body in (('/v1/maintenance/verify',{'request_key':'guard-v','scope':'all'}),('/v1/maintenance/backup',{'request_key':'guard-b','destination_id':'local'})):
            assert browser.post(path,json=body,headers=origin).status_code==403
            assert browser.post(path,json=body,headers={**origin,'X-CSRF-Token':csrf}).status_code==202
        assert browser.patch('/v1/settings/storage',json={'expected_revision':0,'media_root':str(paths.root/'later')},headers=origin).status_code==403
