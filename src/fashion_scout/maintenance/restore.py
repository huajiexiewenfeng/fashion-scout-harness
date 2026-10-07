"""Offline, explicit restore into an empty local target. Never launches services."""
import argparse
from datetime import datetime,timezone
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import uuid
from pydantic import Field
from fashion_scout.domain.models import DTO
from fashion_scout.config import Paths
from fashion_scout.domain import ScoutError
from fashion_scout.exports.engine import no_links,safe_member,ExportError,file_identity
from fashion_scout.services.runs import canonical
from .backup import controlled_id,verify_bundle,asset_name,MAX_DB
from .files import MaintenanceError
from .storage import local_directory


class RestoreInput(DTO):
    backup_id:str=Field(pattern=r'^[a-f0-9]{32}$')
    target:str=Field(min_length=1,max_length=1024)
    allow_partial:bool=False


def verified_file(path,expected,limit):
    """Hash the opened file and reject replacement/change during this bounded read."""
    no_links(path);before=file_identity(path.stat());digest=hashlib.sha256();size=0
    with path.open('rb') as stream:
        if file_identity(os.fstat(stream.fileno()))!=before:raise MaintenanceError('RESTORE_FILE_CHANGED')
        while chunk:=stream.read(1024*1024):
            size+=len(chunk)
            if size>limit or size>expected['bytes']:raise MaintenanceError('RESTORE_FILE_MISMATCH')
            digest.update(chunk)
        if file_identity(os.fstat(stream.fileno()))!=before:raise MaintenanceError('RESTORE_FILE_CHANGED')
    no_links(path)
    if file_identity(path.stat())!=before:raise MaintenanceError('RESTORE_FILE_CHANGED')
    if (digest.hexdigest(),size)!=(expected['sha256'],expected['bytes']):raise MaintenanceError('RESTORE_FILE_MISMATCH')
    return before


def copy_verified(source,target,expected,limit):
    """Bind the bytes actually copied to the initially verified manifest."""
    no_links(source);no_links(target);before=file_identity(source.stat());digest=hashlib.sha256();size=0
    with source.open('rb') as src,target.open('xb') as dst:
        if file_identity(os.fstat(src.fileno()))!=before:raise MaintenanceError('RESTORE_FILE_CHANGED')
        while chunk:=src.read(1024*1024):
            size+=len(chunk)
            if size>limit or size>expected['bytes']:raise MaintenanceError('RESTORE_FILE_MISMATCH')
            digest.update(chunk);dst.write(chunk)
        dst.flush();os.fsync(dst.fileno())
        if file_identity(os.fstat(src.fileno()))!=before:raise MaintenanceError('RESTORE_FILE_CHANGED')
    no_links(source)
    if file_identity(source.stat())!=before:raise MaintenanceError('RESTORE_FILE_CHANGED')
    if (digest.hexdigest(),size)!=(expected['sha256'],expected['bytes']):raise MaintenanceError('RESTORE_FILE_MISMATCH')
    verified_file(target,expected,limit)


def verify_stage(files):
    for path,expected,limit in files:verified_file(path,expected,limit)


def restore(source_root,backup_id,target,allow_partial=False):
    source=Path(source_root).resolve();controlled_id(backup_id)
    destination=local_directory(str(target))
    if destination.is_relative_to(source) or source.is_relative_to(destination):raise ScoutError('RESTORE_TARGET_CONFLICT','恢复目标须与原数据根独立',422)
    no_links(source)
    if destination.exists() and any(destination.iterdir()):raise ScoutError('RESTORE_TARGET_NOT_EMPTY','恢复只允许全新或空目录，不覆盖原库',409)
    bundle=source/'backups'/backup_id
    manifest,digest=verify_bundle(bundle)
    if manifest['backup_id']!=backup_id:raise MaintenanceError('BACKUP_ID_MISMATCH')
    for old in manifest['inventory']['roots'].values():
        old_path=Path(old)
        if destination.is_relative_to(old_path) or old_path.is_relative_to(destination):
            raise ScoutError('RESTORE_TARGET_CONFLICT','恢复目标须与原素材根独立',422)
    if manifest['state']=='partial' and not allow_partial:raise ScoutError('PARTIAL_BACKUP','备份含缺失或未知，请明确允许部分恢复后再运行',409)
    destination.parent.mkdir(parents=True,exist_ok=True);no_links(destination.parent)
    stage=destination.parent/('.scout-restore-'+uuid.uuid4().hex);stage.mkdir()
    inventory=manifest['inventory'];mapping={rid:str(destination/'media'/'roots'/hashlib.sha256(rid.encode()).hexdigest()) for rid in inventory['roots']}
    available={f['path']:f for f in manifest['files']};staged=[]
    for asset in inventory['assets']:
        if asset_name(asset) not in available:continue
        relative=safe_member(asset['relative_path'])
        out=stage/'media'/'roots'/hashlib.sha256(asset['root_id'].encode()).hexdigest()
        out=out.joinpath(*relative.split('/'));out.parent.mkdir(parents=True,exist_ok=True);no_links(out)
        expected=available[asset_name(asset)]
        copy_verified(bundle/asset_name(asset),out,expected,64*1024**2)
        staged.append((out,expected,64*1024**2))
    copy_verified(bundle/'database.sqlite3',stage/'scout.sqlite3',available['database.sqlite3'],MAX_DB)
    # Recheck original DB bytes immediately before intentional mapping SQL.
    verified_file(stage/'scout.sqlite3',available['database.sqlite3'],MAX_DB)
    conn=sqlite3.connect(stage/'scout.sqlite3');conn.row_factory=sqlite3.Row
    try:
        conn.execute('PRAGMA foreign_keys=ON');conn.execute('BEGIN IMMEDIATE')
        prior_runs=[dict(r) for r in conn.execute("SELECT id,state,owner,epoch,lease_until,heartbeat_at,issue_code FROM runs WHERE state IN ('queued','running','interrupted','cancelling')")]
        prior_exports=[dict(r) for r in conn.execute('SELECT id,state,owner,epoch,result_json,roots_json,output_hash FROM export_jobs')]
        prior_maintenance=[dict(r) for r in conn.execute("SELECT id,kind,state,owner,epoch,result_json,output_hash FROM maintenance_jobs WHERE state IN ('queued','running') OR kind='backup'")]
        current=conn.execute('SELECT * FROM storage_preferences WHERE id=1').fetchone()
        preferred=next((mapping[rid] for rid,path in inventory['roots'].items() if current and path==current['media_root']),str(destination/'media'/'current'))
        for rid,path in mapping.items():conn.execute('UPDATE storage_roots SET path=? WHERE id=?',(path,rid))
        conn.execute('INSERT INTO storage_preferences VALUES (1,?,?) ON CONFLICT(id) DO UPDATE SET revision=excluded.revision,media_root=excluded.media_root',((current['revision']+1) if current else 1,preferred))
        conn.execute("INSERT OR IGNORE INTO storage_roots VALUES (?,?,'media')",(hashlib.sha256(preferred.encode()).hexdigest(),preferred))
        conn.execute("UPDATE workers SET state='restored-offline',pid=0,born=0,executable='',heartbeat_at=0")
        conn.execute("UPDATE runs SET state='cancelled',owner=NULL,epoch=epoch+1,lease_until=NULL,heartbeat_at=NULL,cancel_requested=1,issue_code='RESTORED_HELD' WHERE state IN ('queued','running','interrupted','cancelling')")
        for old in prior_runs:
            conn.execute("UPDATE run_attempts SET result_state='cancelled',reason='RESTORED_HELD' WHERE run_id=? AND finished_at IS NULL",(old['id'],))
        for old in prior_exports:
            roots=json.loads(old['roots_json'])
            # Original IDs/snapshot stay; known roots point to restored files.
            roots={rid:mapping[rid] for rid in roots if rid in mapping}
            conn.execute("UPDATE export_jobs SET state='failed',owner=NULL,epoch=epoch+1,lease_until=NULL,heartbeat_at=NULL,result_json=NULL,output_hash=NULL,issue_code='RESTORED_OUTPUT_NOT_INCLUDED',roots_json=? WHERE id=?",(canonical(roots),old['id']))
        conn.execute("UPDATE maintenance_jobs SET state='failed',owner=NULL,epoch=epoch+1,lease_until=NULL,heartbeat_at=NULL,result_json=NULL,output_hash=NULL,issue_code='RESTORED_HELD' WHERE state IN ('queued','running') OR kind='backup'")
        now=datetime.now(timezone.utc).isoformat()
        audit={'old_roots':inventory['roots'],'new_roots':mapping,'prior_runs':prior_runs,'prior_exports':prior_exports,'prior_maintenance':prior_maintenance,
            'source_cooldown':'preserved','services_started':False,'source_requests':0,'issues':manifest['issues']}
        conn.execute('INSERT INTO restore_audit VALUES (?,?,?,?,?,?)',(uuid.uuid4().hex,now,backup_id,digest,manifest['state'],canonical(audit)))
        if conn.execute('PRAGMA foreign_key_check').fetchone():raise MaintenanceError('RESTORE_FOREIGN_KEY_INVALID')
        conn.commit()
        if conn.execute('PRAGMA integrity_check').fetchone()[0]!='ok':raise MaintenanceError('RESTORE_DATABASE_INVALID')
    finally:conn.close()
    # Capture the intentionally rewritten DB, then check it again with assets at publication.
    from .files import hash_file
    db_hash,db_size=hash_file(stage/'scout.sqlite3',limit=MAX_DB)
    staged.append((stage/'scout.sqlite3',{'sha256':db_hash,'bytes':db_size},MAX_DB))
    result={'state':manifest['state'],'backup_id':backup_id,'manifest_sha256':digest,'target':str(destination),'counts':manifest['counts'],
        'issues':manifest['issues'],'services_started':False,'new_runs':0,'old_runtime_held':True,'root_mapping':mapping}
    with (stage/'restore-result.json').open('x',encoding='utf-8') as stream:json.dump(result,stream,ensure_ascii=False,indent=2);stream.flush();os.fsync(stream.fileno())
    # Recheck just before publishing. Never recursively delete or replace a target.
    verify_stage(staged)
    no_links(destination)
    if destination.exists():
        if any(destination.iterdir()):raise ScoutError('RESTORE_TARGET_NOT_EMPTY','恢复期间目标目录已变化',409)
        destination.rmdir()
    os.rename(stage,destination)
    return result


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--data-root',required=True);parser.add_argument('--backup-id')
    parser.add_argument('--target');parser.add_argument('--json-input');parser.add_argument('--allow-partial',action='store_true');args=parser.parse_args()
    try:
        if args.json_input:
            if args.backup_id or args.target or args.allow_partial:raise ValueError('Choose JSON or flags')
            path=Path(args.json_input)
            if path.stat().st_size>1024*1024:raise ValueError('Input limit')
            def pairs(items):
                value={}
                for k,v in items:
                    if k in value:raise ValueError('Duplicate key')
                    value[k]=v
                return value
            payload=RestoreInput.model_validate(json.loads(path.read_text('utf-8'),object_pairs_hook=pairs))
        else:payload=RestoreInput(backup_id=args.backup_id,target=args.target,allow_partial=args.allow_partial)
        result=restore(args.data_root,payload.backup_id,payload.target,payload.allow_partial)
    except ScoutError as exc:result={'error':{'code':exc.code,'message':exc.message}}
    except (MaintenanceError,ExportError) as exc:result={'error':{'code':exc.code,'message':'备份未通过校验，未宣称恢复成功'}}
    except Exception:result={'error':{'code':'RESTORE_FAILED','message':'恢复未完成；保留独立暂存目录供核对，不覆盖原库'}}
    print(json.dumps(result,ensure_ascii=True))
    if 'error' in result:raise SystemExit(1)


if __name__=='__main__':main()
