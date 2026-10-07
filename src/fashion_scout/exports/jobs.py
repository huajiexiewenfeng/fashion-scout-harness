"""Export-only persistence, fenced attempts and controlled package downloads."""
import hashlib
import json
import time
import uuid
from pathlib import Path
from pydantic import Field
from fashion_scout.db import Database
from fashion_scout.domain import ScoutError
from fashion_scout.domain.models import DTO
from fashion_scout.processes import is_dead
from fashion_scout.services.runs import timestamp, digest
from .models import ExportSnapshot, ExportResult, canonical, load_snapshot
from .capture import capture_favorites
from .engine import verify_zip, no_links, file_identity, ExportError


class ExportLease(DTO):
    export_id: str
    owner: str
    epoch: int = Field(gt=0)
    attempt: int = Field(gt=0)


class Jobs:
    def __init__(self,paths,clock=time.time):
        self.paths,self.db,self.clock=paths,Database(paths.db),clock

    @staticmethod
    def row(conn,job_id):
        row=conn.execute('SELECT * FROM export_jobs WHERE id=?',(job_id,)).fetchone()
        if row is None:raise ScoutError('EXPORT_NOT_FOUND','未找到导出任务',404)
        return row

    def create(self,request_key,selection='favorites'):
        payload=digest({'action':'create','selection':selection})
        with self.db.write() as conn:
            prior=conn.execute('SELECT * FROM export_requests WHERE request_key=?',(request_key,)).fetchone()
            if prior:
                if prior['payload_hash']!=payload:raise ScoutError('REQUEST_KEY_CONFLICT','此意图键已用于不同操作',409)
                return prior['export_id'],True
            jid=uuid.uuid4().hex;now=timestamp(self.clock())
            snapshot,roots=capture_favorites(conn,jid,now)
            scopes=['product.images'] if snapshot.schema_version==1 else sorted({v.coverage_scope for p in snapshot.products for v in p.versions})
            conn.execute('INSERT INTO export_jobs(id,request_key,state,snapshot_json,promised_coverage_json,required_coverage_json,capability_notes_json,roots_json,snapshot_hash,created_at) VALUES (?,?,\'queued\',?,?,?,?,?,?,?)',
                (jid,request_key,snapshot.model_dump_json(),canonical(scopes),canonical([p.model_dump(mode='json') for p in snapshot.products]),canonical([n.model_dump() for p in snapshot.products for n in p.capability_notes]),canonical(roots),snapshot.digest,now))
            conn.execute('INSERT INTO export_attempts(export_id,number,created_at,state) VALUES (?,1,?,\'queued\')',(jid,now))
            conn.execute('INSERT INTO export_requests VALUES (?,?,?,?,?)',(request_key,payload,jid,'create',now))
            for p in snapshot.products:conn.execute('INSERT INTO export_members VALUES (?,?,?)',(jid,p.product_id,p.model_dump_json()))
            for a in snapshot.assets:conn.execute('INSERT INTO export_assets VALUES (?,?,?)',(jid,a.asset_id,a.model_dump_json()))
            return jid,False

    def retry(self,jid,request_key):
        payload=digest({'action':'retry','export_id':jid})
        with self.db.write() as conn:
            row=self.row(conn,jid)
            prior=conn.execute('SELECT * FROM export_requests WHERE request_key=?',(request_key,)).fetchone()
            if prior:
                if prior['payload_hash']!=payload:raise ScoutError('REQUEST_KEY_CONFLICT','此意图键已用于不同操作',409)
                return True
            if row['state'] in {'queued','running'}:raise ScoutError('EXPORT_ACTIVE','此导出仍在处理中',409)
            now=timestamp(self.clock());number=row['attempt']+1
            conn.execute("UPDATE export_jobs SET state='queued',attempt=?,epoch=epoch+1,owner=NULL,lease_until=NULL,finished_at=NULL,output_hash=NULL,result_json=NULL,issue_code=NULL WHERE id=?",(number,jid))
            conn.execute("INSERT INTO export_attempts(export_id,number,created_at,state) VALUES (?,?,?,'queued')",(jid,number,now))
            conn.execute('INSERT INTO export_requests VALUES (?,?,?,?,?)',(request_key,payload,jid,'retry',now))
            return False

    def snapshot(self,row):
        value=load_snapshot(row['snapshot_json'])
        if value.export_id!=row['id'] or value.digest!=row['snapshot_hash']:
            raise ScoutError('EXPORT_SNAPSHOT_CONFLICT','已保存导出范围发生变化',409)
        return value

    def directory(self,jid,attempt):
        if len(jid)!=32 or any(c not in '0123456789abcdef' for c in jid) or type(attempt) is not int or attempt<1:
            raise ScoutError('EXPORT_PATH_INVALID','导出存储标识无效',410)
        path=self.paths.root/'exports'/jid/f'attempt-{attempt:06d}'
        no_links(path)
        if not path.resolve().is_relative_to(self.paths.root):raise ScoutError('EXPORT_PATH_INVALID','导出存储越界',410)
        return path

    def get(self,jid):
        with self.db.read() as conn:
            row=self.row(conn,jid);snap=self.snapshot(row)
            worker=conn.execute("SELECT * FROM workers WHERE state='online' ORDER BY heartbeat_at DESC LIMIT 1").fetchone()
            online=bool(worker and self.clock()-worker['heartbeat_at']<30 and not is_dead(dict(worker)))
        result=json.loads(row['result_json']) if row['result_json'] else {}
        ready=row['state'] in {'succeeded','partial'} and bool(row['output_hash'])
        issues=[row['issue_code']] if row['issue_code'] else []
        if ready:
            try:
                stream,_=self.download(jid);stream.close()
            except ScoutError as exc:
                ready=False;issues.append(exc.code)
        return {'id':jid,'state':row['state'],'created_at':row['created_at'],'finished_at':row['finished_at'],
            'attempt':row['attempt'],'resumed_at':row['resumed_at'],'worker_state':'online' if online else 'offline',
            'counts':{'products':len(snap.products),'assets':len(snap.assets)},
            'missing_count':result.get('missing_count',0),'unknown_count':result.get('unknown_count',0),
            'issues':issues,
            'download_url':f'/v1/exports/{jid}/download' if ready else None,'sha256':row['output_hash'] if ready else None}

    def download(self,jid):
        with self.db.read() as conn:row=dict(self.row(conn,jid))
        if row['state'] not in {'succeeded','partial'} or not row['output_hash']:
            raise ScoutError('EXPORT_NOT_READY','导出还未就绪',409)
        stream=None
        try:
            snap=self.snapshot(row);result=ExportResult.model_validate_json(row['result_json'])
            path=self.directory(jid,row['attempt'])/('export-'+hashlib.sha256(jid.encode()).hexdigest()+'.zip')
            if result.path!=str(path) or result.snapshot_sha256!=snap.digest or result.sha256!=row['output_hash']:
                raise ValueError()
            before=file_identity(path.stat());manifest=verify_zip(path,snap)
            stream=path.open('rb')
            if file_identity(__import__('os').fstat(stream.fileno()))!=before:raise ValueError()
            if hashlib.file_digest(stream,'sha256').hexdigest()!=row['output_hash'] or path.stat().st_size!=result.bytes:
                raise ValueError()
            if manifest['state']!=row['state'] or file_identity(path.stat())!=before:raise ValueError()
            stream.seek(0)
            return stream,result.bytes
        except (OSError,ValueError,ExportError,ScoutError):
            if stream:stream.close()
            raise ScoutError('EXPORT_UNAVAILABLE','导出文件已丢失或未通过核验，请显式重试此导出',410) from None

    def fence(self,conn,lease):
        row=self.row(conn,lease.export_id)
        if row['owner']!=lease.owner or row['epoch']!=lease.epoch or row['attempt']!=lease.attempt or row['state']!='running':
            raise ScoutError('STALE_EXPORT_LEASE','导出执行权已失效',409)
        return row

    def claim(self,owner,lease_seconds=30):
        with self.db.write() as conn:
            if not conn.execute("SELECT 1 FROM workers WHERE id=? AND state='online'",(owner,)).fetchone():
                raise ScoutError('WORKER_NOT_REGISTERED','执行器未登记',409)
            row=conn.execute("SELECT * FROM export_jobs WHERE state='queued' ORDER BY created_at,id LIMIT 1").fetchone()
            if row is None:return None
            now=self.clock();epoch=row['epoch']+1
            conn.execute("UPDATE export_jobs SET state='running',owner=?,epoch=?,lease_until=?,heartbeat_at=? WHERE id=?",(owner,epoch,now+lease_seconds,now,row['id']))
            conn.execute("UPDATE export_attempts SET state='running',started_at=COALESCE(started_at,?) WHERE export_id=? AND number=?",(timestamp(now),row['id'],row['attempt']))
            return ExportLease(export_id=row['id'],owner=owner,epoch=epoch,attempt=row['attempt'])

    def heartbeat(self,lease,seconds):
        with self.db.write() as conn:
            self.fence(conn,lease)
            conn.execute('UPDATE export_jobs SET heartbeat_at=?,lease_until=? WHERE id=?',(self.clock(),self.clock()+seconds,lease.export_id))

    def release(self,lease):
        with self.db.write() as conn:
            self.fence(conn,lease)
            conn.execute("UPDATE export_jobs SET state='queued',owner=NULL,epoch=epoch+1,lease_until=NULL,resumed_at=? WHERE id=?",(timestamp(self.clock()),lease.export_id))

    def recover(self,owner_is_dead=is_dead):
        with self.db.read() as conn:
            rows=[dict(r) for r in conn.execute("SELECT j.*,w.pid,w.born,w.executable FROM export_jobs j JOIN workers w ON w.id=j.owner WHERE j.state='running'")]
        for old in rows:
            # A confirmed dead process may be recovered before lease timeout. Time
            # alone never authorizes takeover of a still-live or unknown process.
            if not owner_is_dead(old):continue
            with self.db.write() as conn:
                row=self.row(conn,old['id'])
                if row['state']!='running' or row['epoch']!=old['epoch'] or row['owner']!=old['owner']:continue
                conn.execute("UPDATE export_jobs SET state='queued',owner=NULL,epoch=epoch+1,lease_until=NULL,resumed_at=? WHERE id=?",(timestamp(self.clock()),old['id']))

    def work(self,lease):
        with self.db.read() as conn:row=self.fence(conn,lease)
        return self.snapshot(row),json.loads(row['roots_json']),self.directory(lease.export_id,lease.attempt)

    def finish(self,lease,result):
        with self.db.write() as conn:
            row=self.fence(conn,lease)
            if result.snapshot_sha256!=row['snapshot_hash']:raise ScoutError('EXPORT_SNAPSHOT_CONFLICT','导出结果范围不符',409)
            now=timestamp(self.clock())
            conn.execute('UPDATE export_jobs SET state=?,finished_at=?,lease_until=NULL,result_json=?,output_hash=?,issue_code=? WHERE id=?',
                (result.state,now,result.model_dump_json(),result.sha256,result.error_code,lease.export_id))
            conn.execute('UPDATE export_attempts SET state=?,finished_at=?,result_json=? WHERE export_id=? AND number=?',
                (result.state,now,result.model_dump_json(),lease.export_id,lease.attempt))
