import json
import threading
import time
from fashion_scout.domain import ScoutError
from fashion_scout.exports.engine import ExportError
from .jobs import Jobs
from .files import MaintenanceError,verify_inventory
from .backup import backup


class Interrupted(Exception):pass


class MaintenanceRunner:
    def __init__(self,paths,owner,stopped,worker_heartbeat):
        self.paths,self.jobs,self.owner,self.stopped,self.worker_heartbeat=paths,Jobs(paths),owner,stopped,worker_heartbeat

    def execute(self,lease):
        done,lost=threading.Event(),threading.Event()
        def beat():
            while not done.wait(3):
                try:self.jobs.heartbeat(lease);self.worker_heartbeat()
                except Exception:lost.set();return
        thread=threading.Thread(target=beat,daemon=True);thread.start()
        def check():
            if self.stopped() or lost.is_set():raise Interrupted()
            with self.jobs.db.read() as conn:self.jobs.fence(conn,lease)
        try:
            check()
            with self.jobs.db.read() as conn:row=self.jobs.fence(conn,lease);snapshot=json.loads(row['snapshot_json'])
            try:result=verify_inventory(snapshot['inventory'],check) if row['kind']=='verify' else backup(self.paths,lease.job_id,check)
            except (MaintenanceError,ExportError) as exc:result={'state':'failed','error_code':exc.code,'issues':[]}
            except (OSError,ValueError,KeyError):result={'state':'failed','error_code':'MAINTENANCE_IO_ERROR','issues':[]}
            check();self.jobs.finish(lease,result)
        except Interrupted:
            self.jobs.release(lease)
        except ScoutError as exc:
            if exc.code!='STALE_MAINTENANCE_LEASE':raise
        finally:done.set();thread.join(timeout=4)

    def run(self):
        pending=None
        while not self.stopped():
            try:
                if pending:
                    try:self.jobs.release(pending)
                    except ScoutError as exc:
                        if exc.code!='STALE_MAINTENANCE_LEASE':raise
                    pending=None
                self.jobs.recover();lease=self.jobs.claim(self.owner)
                if lease:pending=lease;self.execute(lease);pending=None
                else:time.sleep(.25)
            except Exception:time.sleep(.5)
