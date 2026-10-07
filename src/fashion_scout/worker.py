"""Persistent worker. Only an explicitly accepted Run invokes the collection executor."""
import argparse
import threading
import time
import uuid

from .config import Paths
from .db import Database
from .db.archive import Archive
from .domain import Outcome, ScoutError
from .processes import identity, is_dead, publish_identity
from .services.runs import Runs
from .services.browser_acquisition import BrowserAcquisition, SourceWait


class StopRequested(Exception):
    pass


class Context:
    def __init__(self, runs, lease, stopped, lost):
        self.runs, self.lease, self.stopped, self.lost = runs, lease, stopped, lost
        self.archive_recovery = None
        # One monotonic budget per owned execution; offline/cooldown between leases
        # does not consume the next execution's active time allowance.
        self.collection_started = time.monotonic()

    def checkpoint(self):
        if self.lost.is_set():
            raise ScoutError("STALE_LEASE", "Heartbeat could not retain lease")
        if self.stopped():
            raise StopRequested()
        if self.runs.cancellation_requested(self.lease):
            raise ScoutError("CANCEL_REQUESTED", "Run cancelled at safe boundary")


def unavailable_executor(context):
    context.checkpoint()
    raise ScoutError("ADAPTER_NOT_IMPLEMENTED", "T1 has no source-site adapter", 503)


class Worker:
    def __init__(self, paths: Paths, stopped, executor=None,
                 heartbeat_seconds=10.0, lease_seconds=60.0, poll_seconds=0.25):
        if not 0 < heartbeat_seconds < lease_seconds:
            raise ValueError("Heartbeat interval must be smaller than lease")
        from .services.collect import production_executor
        self.paths, self.stopped, self.executor = paths, stopped, executor or production_executor
        self.heartbeat_seconds, self.lease_seconds, self.poll_seconds = heartbeat_seconds, lease_seconds, poll_seconds
        self.runs = Runs(Database(paths.db))
        self.owner = uuid.uuid4().hex
        self.recovered = []

    def run(self):
        who = identity()
        self.runs.register_worker(self.owner, who["pid"], who["born"], who["executable"])
        from .exports.runner import ExportRunner
        export_stop = threading.Event()
        export_runner = ExportRunner(self.paths, self.owner,
            lambda: export_stop.is_set() or self.stopped(),
            lambda: self.runs.worker_heartbeat(self.owner))
        export_thread = threading.Thread(target=export_runner.run, name='export-lane', daemon=True)
        export_thread.start()
        from .maintenance.runner import MaintenanceRunner
        maintenance_runner=MaintenanceRunner(self.paths,self.owner,
            lambda: export_stop.is_set() or self.stopped(),lambda: self.runs.worker_heartbeat(self.owner))
        maintenance_thread=threading.Thread(target=maintenance_runner.run,name='maintenance-lane',daemon=True)
        maintenance_thread.start()
        try:
            while not self.stopped():
                self.runs.worker_heartbeat(self.owner)
                self.recovered.extend(self.runs.recover_expired(is_dead))
                lease = self.runs.claim(self.owner, self.lease_seconds)
                if lease is None:
                    time.sleep(self.poll_seconds)
                    continue
                lost, done = threading.Event(), threading.Event()

                def heartbeat():
                    while not done.wait(self.heartbeat_seconds):
                        try:
                            self.runs.heartbeat(lease, self.lease_seconds)
                            self.runs.worker_heartbeat(self.owner)
                        except Exception:
                            lost.set()
                            return

                thread = threading.Thread(target=heartbeat, daemon=True)
                thread.start()
                try:
                    context = Context(self.runs, lease, self.stopped, lost)
                    context.paths = self.paths.for_run(lease.run_id)
                    context.checkpoint()
                    result = Archive(context.paths, self.runs).recover(lease)
                    context.archive_recovery = result
                    if result["fatal_failures"]:
                        raise ScoutError("ARCHIVE_RECOVERY_REQUIRED", "Storage environment requires reconciliation")
                    outcome = self.executor(context)
                    context.checkpoint()
                    self.runs.finish(lease, outcome)
                except StopRequested:
                    if self.runs.get(lease.run_id).snapshot.source_mode == "browser" and not self.runs.cancellation_requested(lease):
                        BrowserAcquisition(self.runs).suspend(lease)
                    else:
                        self.runs.release(lease)
                    return
                except SourceWait:
                    BrowserAcquisition(self.runs).suspend(lease)
                    continue
                except ScoutError as exc:
                    if exc.code == "STALE_LEASE" or lost.is_set():
                        return  # Exit so expired lease can be recovered, never steal live ownership.
                    self.runs.finish(lease, Outcome(state="failed", valid_results=0,
                        coverage_complete=False, required_complete=False,
                        evidence_ref="worker:" + exc.code, issue_code=exc.code))
                except Exception:
                    # No exception repr / credentials from adapter code in persisted diagnostics.
                    self.runs.finish(lease, Outcome(state="failed", valid_results=0,
                        coverage_complete=False, required_complete=False,
                        evidence_ref="worker:EXECUTOR_ERROR", issue_code="EXECUTOR_ERROR"))
                finally:
                    done.set()
                    thread.join(timeout=self.heartbeat_seconds + 1)
        finally:
            export_stop.set()
            maintenance_thread.join()
            export_thread.join()
            self.runs.stop_worker(self.owner)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-root", required=True)
    parser.add_argument("--instance", required=True)
    args = parser.parse_args()
    paths = Paths.at(args.data_root)
    publish_identity(paths, args.instance, 'worker')
    stop_file = paths.root / "control" / (args.instance + ".stop")
    Worker(paths, stop_file.exists).run()


if __name__ == "__main__":
    main()
