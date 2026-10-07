from dataclasses import dataclass
import json
import time
import uuid
from fashion_scout.db import Database
from fashion_scout.domain import ScoutError
from fashion_scout.processes import is_dead
from fashion_scout.services.runs import canonical,digest,timestamp
from .inventory import capture
from .presentation import finding_groups


@dataclass(frozen=True)
class Lease:
    job_id:str
    owner:str
    epoch:int


class Jobs:
    def __init__(self,paths,clock=time.time):self.paths,self.db,self.clock=paths,Database(paths.db),clock

    def row(self,conn,jid):
        row=conn.execute('SELECT * FROM maintenance_jobs WHERE id=?',(jid,)).fetchone()
        if row is None:raise ScoutError('MAINTENANCE_NOT_FOUND','未找到维护任务',404)
        return row

    def create(self,kind,key,options):
        payload=digest({'kind':kind,**options})
        with self.db.write() as conn:
            old=conn.execute('SELECT * FROM maintenance_requests WHERE request_key=?',(key,)).fetchone()
            if old:
                if old['payload_hash']!=payload:raise ScoutError('REQUEST_KEY_CONFLICT','此意图键已用于不同操作',409)
                return old['job_id'],True
            jid=uuid.uuid4().hex
            snapshot={'kind':kind,'options':options}
            if kind=='verify':snapshot['inventory']=capture(conn,options['scope'],options.get('product_ids',()))
            elif kind=='backup':snapshot['destination']=str(self.paths.root/'backups')
            else:raise ScoutError('INVALID_MAINTENANCE','维护类型无效',422)
            conn.execute("INSERT INTO maintenance_jobs(id,kind,state,snapshot_json,request_key,created_at) VALUES (?,?,'queued',?,?,?)",(jid,kind,canonical(snapshot),key,timestamp(self.clock())))
            conn.execute('INSERT INTO maintenance_requests VALUES (?,?,?)',(key,payload,jid))
            return jid,False

    def get(self,jid):
        with self.db.read() as conn:
            row=dict(self.row(conn,jid));worker=conn.execute("SELECT * FROM workers WHERE state='online' ORDER BY heartbeat_at DESC LIMIT 1").fetchone()
            online=bool(worker and self.clock()-worker['heartbeat_at']<30 and not is_dead(dict(worker)))
        result=json.loads(row['result_json']) if row['result_json'] else {}
        inventory=json.loads(row['snapshot_json']).get('inventory',{})
        available=None
        if row['kind']=='backup' and row['state'] in {'succeeded','partial'}:
            available=False
            try:
                from .backup import controlled_id,verify_bundle
                target=self.paths.root/'backups'/controlled_id(jid)
                if result.get('path')!=str(target):raise ValueError()
                manifest,_=verify_bundle(target,row['output_hash']);inventory=manifest['inventory'];available=True
            except Exception:
                result={**result,'path':None};row['issue_code']='BACKUP_UNAVAILABLE'
        return {'id':jid,'kind':row['kind'],'state':row['state'],'created_at':row['created_at'],'finished_at':row['finished_at'],
            'resumed_at':row['resumed_at'],'worker_state':'online' if online else 'offline','result':result,'issue_code':row['issue_code'],'backup_available':available,
            'finding_groups':finding_groups(result.get('issues',[]),inventory)}

    def recent(self):
        with self.db.read() as conn:ids=[r[0] for r in conn.execute('SELECT id FROM maintenance_jobs ORDER BY created_at DESC,id DESC LIMIT 10')]
        return [self.get(jid) for jid in ids]

    def fence(self,conn,lease):
        row=self.row(conn,lease.job_id)
        if (row['state'],row['owner'],row['epoch'])!=('running',lease.owner,lease.epoch):raise ScoutError('STALE_MAINTENANCE_LEASE','维护执行权已失效',409)
        return row

    def claim(self,owner):
        with self.db.write() as conn:
            if not conn.execute("SELECT 1 FROM workers WHERE id=? AND state='online'",(owner,)).fetchone():raise ScoutError('WORKER_NOT_REGISTERED','执行器未登记',409)
            row=conn.execute("SELECT * FROM maintenance_jobs WHERE state='queued' ORDER BY created_at,id LIMIT 1").fetchone()
            if row is None:return None
            epoch=row['epoch']+1;now=self.clock()
            conn.execute("UPDATE maintenance_jobs SET state='running',owner=?,epoch=?,lease_until=?,heartbeat_at=? WHERE id=?",(owner,epoch,now+30,now,row['id']))
            return Lease(row['id'],owner,epoch)

    def heartbeat(self,lease):
        with self.db.write() as conn:
            self.fence(conn,lease);now=self.clock()
            conn.execute('UPDATE maintenance_jobs SET heartbeat_at=?,lease_until=? WHERE id=?',(now,now+30,lease.job_id))

    def release(self,lease):
        with self.db.write() as conn:
            self.fence(conn,lease)
            conn.execute("UPDATE maintenance_jobs SET state='queued',owner=NULL,epoch=epoch+1,lease_until=NULL,resumed_at=? WHERE id=?",(timestamp(self.clock()),lease.job_id))

    def recover(self,dead=is_dead):
        with self.db.read() as conn:rows=[dict(r) for r in conn.execute("SELECT j.*,w.pid,w.born,w.executable FROM maintenance_jobs j JOIN workers w ON w.id=j.owner WHERE j.state='running'")]
        for old in rows:
            if not dead(old):continue
            try:self.release(Lease(old['id'],old['owner'],old['epoch']))
            except ScoutError as exc:
                if exc.code!='STALE_MAINTENANCE_LEASE':raise

    def finish(self,lease,result):
        with self.db.write() as conn:
            row=self.fence(conn,lease);now=timestamp(self.clock())
            result={**result,'checked_at':now}
            conn.execute('UPDATE maintenance_jobs SET state=?,finished_at=?,lease_until=NULL,result_json=?,output_hash=?,issue_code=? WHERE id=?',
                (result['state'],now,canonical(result),result.get('manifest_sha256'),result.get('error_code'),lease.job_id))
            if row['kind']=='verify' and result['state']!='failed':
                inventory=json.loads(row['snapshot_json'])['inventory']
                objects={'asset:'+a['id'] for a in inventory['assets']}|{'product:'+p for p in inventory['products']}|{i['object_id'] for i in inventory['issues']}
                objects|={f"version:{v['id']}:{v['revision']}" for v in inventory['versions']}
                objects|={f"version:{r['version_id']}:{r['revision']}:{r['source_image_id']}" for r in inventory['relations']}
                for obj in objects:conn.execute('UPDATE maintenance_findings SET resolved=1,checked_at=?,last_job_id=? WHERE object_id=?',(now,lease.job_id,obj))
                for issue in result['issues']:
                    conn.execute('INSERT INTO maintenance_findings VALUES (?,?,?,?,?,0) ON CONFLICT(object_id,code) DO UPDATE SET last_job_id=excluded.last_job_id,checked_at=excluded.checked_at,resolved=0',
                        (issue['object_id'],issue['code'],issue['category'],lease.job_id,now))
