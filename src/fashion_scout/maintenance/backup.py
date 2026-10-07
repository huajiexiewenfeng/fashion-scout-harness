"""Consistent SQLite backup plus verified real assets, never a live .db copy."""
from datetime import datetime,timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import time
import uuid
from fashion_scout.exports.engine import no_links
from fashion_scout.services.runs import canonical
from .files import check_asset,hash_file,MaintenanceError,MAX_TOTAL
from .inventory import capture

MAX_DB=512*1024**2
MAX_META=64*1024**2


def controlled_id(jid):
    if len(jid)!=32 or any(c not in '0123456789abcdef' for c in jid):raise MaintenanceError('INVALID_BACKUP_ID')
    return jid


def asset_name(a):return 'assets/'+hashlib.sha256(a['id'].encode()).hexdigest()+'.bin'


def database_inventory(path):
    no_links(path)
    if path.stat().st_size>MAX_DB:raise MaintenanceError('DATABASE_LIMIT')
    conn=sqlite3.connect(path.as_uri()+'?mode=ro',uri=True);conn.row_factory=sqlite3.Row
    try:
        if conn.execute('PRAGMA integrity_check').fetchone()[0]!='ok' or conn.execute('PRAGMA foreign_key_check').fetchone():raise MaintenanceError('DATABASE_INVALID')
        return capture(conn,all_assets=True)
    finally:conn.close()


def freeze_database(paths,jid,work,checkpoint):
    final=work/'snapshot.sqlite3'
    if final.exists():database_inventory(final);return final
    if len(list(work.glob('snapshot-*.sqlite3')))>=3:raise MaintenanceError('STAGING_LIMIT')
    temp=work/('snapshot-'+uuid.uuid4().hex+'.sqlite3')
    start=time.monotonic()
    def progress(status,remaining,total):
        checkpoint()
        if time.monotonic()-start>120 or total*4096>MAX_DB:raise MaintenanceError('DATABASE_BACKUP_LIMIT')
    source=sqlite3.connect(paths.db.as_uri()+'?mode=ro',uri=True)
    destination=sqlite3.connect(temp)
    try:
        source.backup(destination,pages=256,progress=progress,sleep=.01)
        destination.execute('PRAGMA journal_mode=DELETE')
        destination.commit()
    finally:destination.close();source.close()
    database_inventory(temp)
    with temp.open('r+b') as stream:os.fsync(stream.fileno())
    checkpoint()
    try:os.link(temp,final)
    except FileExistsError:database_inventory(final)
    finally:temp.unlink(missing_ok=True)
    return final


def copy_bytes(source,target,checkpoint,limit):
    with source.open('rb') as src,target.open('xb') as dst:
        size=0
        while chunk:=src.read(1024*1024):
            checkpoint();size+=len(chunk)
            if size>limit:raise MaintenanceError('FILE_LIMIT')
            dst.write(chunk)
        dst.flush();os.fsync(dst.fileno())


def read_json(path,limit=MAX_META):
    no_links(path)
    if path.stat().st_size>limit:raise MaintenanceError('METADATA_LIMIT')
    return json.loads(path.read_text('utf-8'))


def summary(inventory,failures):
    issues=inventory['issues']+failures
    return {'state':'partial' if issues else 'succeeded','counts':{'products':len(inventory['products']),'assets':len(inventory['assets']),
        'verified':len(inventory['assets'])-len(failures),**{c:sum(i['category']==c for i in issues) for c in ('missing','damaged','unknown')}},'issues':issues}


def verify_bundle(bundle,expected_hash=None,checkpoint=lambda:None):
    """Verify only this package; no old root or live DB access."""
    bundle=Path(bundle);no_links(bundle)
    commit=read_json(bundle/'COMMIT.json',4096)
    manifest_hash,_=hash_file(bundle/'manifest.json',checkpoint,MAX_META)
    if commit!={'manifest_sha256':manifest_hash} or expected_hash and expected_hash!=manifest_hash:raise MaintenanceError('BACKUP_HASH_MISMATCH')
    manifest=read_json(bundle/'manifest.json')
    if manifest.get('schema')!=1:raise MaintenanceError('BACKUP_SCHEMA_UNSUPPORTED')
    controlled_id(manifest['backup_id'])
    inventory=database_inventory(bundle/'database.sqlite3')
    if inventory!=manifest['inventory']:raise MaintenanceError('BACKUP_RANGE_MISMATCH')
    failures=manifest['asset_failures'];asset_map={a['id']:a for a in inventory['assets']}
    failed=set()
    for issue in failures:
        if set(issue)!={'object_id','code','category'} or issue['category'] not in {'missing','damaged','unknown'} or not issue['object_id'].startswith('asset:'):raise MaintenanceError('BACKUP_MANIFEST_INVALID')
        aid=issue['object_id'][6:]
        if aid not in asset_map or aid in failed:raise MaintenanceError('BACKUP_MANIFEST_INVALID')
        failed.add(aid)
    expected={'database.sqlite3':None,**{asset_name(a):a for a in inventory['assets'] if a['id'] not in failed}}
    files=manifest['files']
    if len(files)!=len(expected) or {f['path'] for f in files}!=set(expected):raise MaintenanceError('BACKUP_MEMBERS_INVALID')
    actual=set()
    for p in bundle.rglob('*'):
        no_links(p)
        if p.is_file():actual.add(p.relative_to(bundle).as_posix())
    if actual!=set(expected)|{'manifest.json','COMMIT.json'}:raise MaintenanceError('BACKUP_MEMBERS_INVALID')
    for f in files:
        a=expected[f['path']]
        digest,size=hash_file(bundle/f['path'],checkpoint,MAX_DB if a is None else 64*1024**2)
        if (digest,size)!=(f['sha256'],f['bytes']) or a and (digest,size)!=(a['sha256'],a['bytes']):raise MaintenanceError('BACKUP_HASH_MISMATCH')
    truth=summary(inventory,failures)
    if any(manifest[k]!=truth[k] for k in ('state','counts','issues')):raise MaintenanceError('BACKUP_MANIFEST_INVALID')
    return manifest,manifest_hash


def backup(paths,jid,checkpoint=lambda:None):
    controlled_id(jid)
    output=paths.root/'backups';work=paths.root/'maintenance'/jid
    no_links(output);no_links(work);output.mkdir(exist_ok=True);work.mkdir(parents=True,exist_ok=True)
    final=output/jid
    if final.exists():
        manifest,digest=verify_bundle(final,checkpoint=checkpoint)
        if manifest['backup_id']!=jid:raise MaintenanceError('BACKUP_ID_MISMATCH')
        return {**{k:manifest[k] for k in ('state','counts','issues')},'path':str(final),'manifest_sha256':digest,'reused':True,'backup_id':jid}
    if len(list(work.glob('stage-*')))>2:raise MaintenanceError('STAGING_LIMIT')
    database=freeze_database(paths,jid,work,checkpoint);inventory=database_inventory(database)
    conn=sqlite3.connect(database)
    try:
        row=conn.execute('SELECT kind FROM maintenance_jobs WHERE id=?',(jid,)).fetchone()
        if row!=('backup',):raise MaintenanceError('BACKUP_SNAPSHOT_CONFLICT')
    finally:conn.close()
    total=sum(a['bytes'] for a in inventory['assets'])
    if total>MAX_TOTAL:raise MaintenanceError('BACKUP_LIMIT')
    if shutil.disk_usage(output).free<total+MAX_META+64*1024**2+database.stat().st_size:raise MaintenanceError('DISK_RESERVE')
    stage=work/('stage-'+uuid.uuid4().hex[:12]);stage.mkdir();(stage/'assets').mkdir()
    copy_bytes(database,stage/'database.sqlite3',checkpoint,MAX_DB)
    db_hash,db_bytes=hash_file(stage/'database.sqlite3',checkpoint,MAX_DB)
    files=[{'path':'database.sqlite3','sha256':db_hash,'bytes':db_bytes}];failures=[]
    for asset in inventory['assets']:
        target=stage/asset_name(asset)
        issue=check_asset(asset,inventory['roots'],target,checkpoint)
        if issue:
            failures.append(issue);target.unlink(missing_ok=True)
        else:files.append({'path':asset_name(asset),'sha256':asset['sha256'],'bytes':asset['bytes']})
    manifest={'schema':1,'backup_id':jid,'snapshot_at':datetime.fromtimestamp(database.stat().st_mtime,timezone.utc).isoformat(),'inventory':inventory,'files':files,
        'asset_failures':failures,**summary(inventory,failures)}
    raw=canonical(manifest).encode('utf-8')
    if len(raw)>MAX_META:raise MaintenanceError('METADATA_LIMIT')
    for name,data in [('manifest.json',raw),('COMMIT.json',canonical({'manifest_sha256':hashlib.sha256(raw).hexdigest()}).encode())]:
        with (stage/name).open('xb') as stream:stream.write(data);stream.flush();os.fsync(stream.fileno())
    verify_bundle(stage,checkpoint=checkpoint);checkpoint()
    # This project is Windows-only: rename fails if destination already exists.
    try:os.rename(stage,final)
    except FileExistsError:pass
    manifest,digest=verify_bundle(final,checkpoint=checkpoint)
    return {**{k:manifest[k] for k in ('state','counts','issues')},'path':str(final),'manifest_sha256':digest,'reused':False,'backup_id':jid}
