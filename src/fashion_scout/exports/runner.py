"""One bounded export lane inside the existing independently hosted Worker."""
import threading
import time
from fashion_scout.domain import ScoutError
from .engine import export_zip
from .jobs import Jobs


class ExportInterrupted(Exception):pass


class ExportRunner:
    def __init__(self,paths,owner,stopped,worker_heartbeat,heartbeat_seconds=3,lease_seconds=30):
        self.jobs=Jobs(paths);self.owner=owner;self.stopped=stopped
        self.worker_heartbeat=worker_heartbeat
        self.heartbeat_seconds=heartbeat_seconds;self.lease_seconds=lease_seconds

    def execute(self,lease):
        done,lost=threading.Event(),threading.Event()
        def beat():
            while not done.wait(self.heartbeat_seconds):
                try:
                    self.jobs.heartbeat(lease,self.lease_seconds);self.worker_heartbeat()
                except Exception:lost.set();return
        thread=threading.Thread(target=beat,daemon=True);thread.start()
        def check():
            if self.stopped() or lost.is_set():raise ExportInterrupted()
            with self.jobs.db.read() as conn:self.jobs.fence(conn,lease)
        try:
            check();snapshot,roots,directory=self.jobs.work(lease)
            result=export_zip(snapshot,roots,directory,checkpoint=check)
            check()
            self.jobs.finish(lease,result)
        except (ExportInterrupted,ScoutError):
            try:self.jobs.release(lease)
            except ScoutError:pass
        finally:
            done.set();thread.join(timeout=self.heartbeat_seconds+1)

    def run(self):
        pending=None
        while not self.stopped():
            try:
                if pending:
                    try:self.jobs.release(pending)
                    except ScoutError as exc:
                        if exc.code!='STALE_EXPORT_LEASE':raise
                    pending=None
                self.worker_heartbeat()
                self.jobs.recover()
                lease=self.jobs.claim(self.owner,self.lease_seconds)
                if lease:
                    pending=lease
                    self.execute(lease)
                    pending=None
                else:time.sleep(.25)
            except Exception:
                # Never mark a potentially published ZIP as business failure because
                # its completion transaction failed. Retire this lane's live claims
                # cooperatively; next iteration reuses the same attempt directory.
                time.sleep(.5)
