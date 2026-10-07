import hashlib
import json
import time
import uuid
from datetime import datetime, timedelta, timezone
from typing import Callable

from fashion_scout.db import Database
from fashion_scout.domain import CreateRun, DefaultPlan, Lease, Outcome, RunView, ScoutError, Snapshot
from fashion_scout.domain.models import CreateResult, run_request_payload, effective_browser_defaults
from fashion_scout.domain.sites import BROWSER_SITES

ACTIVE = ("queued", "running", "interrupted", "cancelling")


def timestamp(now: float) -> str:
    return datetime.fromtimestamp(now, timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def canonical(value) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def digest(value) -> str:
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def new_id() -> str:
    return uuid.uuid4().hex


class Runs:
    def __init__(self, db: Database, clock: Callable[[], float] = time.time):
        self.db, self.clock = db, clock

    def initialize(self):
        self.db.initialize()
        with self.db.write() as conn:
            conn.execute("INSERT OR IGNORE INTO settings VALUES (1,1,?)", (DefaultPlan().model_dump_json(),))
            conn.execute("INSERT OR IGNORE INTO sites(id,entry,adapter_version,enabled) VALUES (?,?,?,1)",
                         ("futario", "https://futario.com/collections/new-in", "futario-json-v1"))
            conn.execute("UPDATE sites SET adapter_version='futario-json-v1' WHERE id='futario' AND adapter_version='not-implemented'")
            for site in BROWSER_SITES.values():
                if site.id != "futario":
                    conn.execute("INSERT OR IGNORE INTO sites(id,entry,adapter_version,enabled) VALUES (?,?,?,1)",
                                 (site.id, site.entry, site.adapter_version))

    @staticmethod
    def _view(row) -> RunView:
        if row is None:
            raise ScoutError("RUN_NOT_FOUND", "Run does not exist", 404)
        return RunView(id=row["id"], state=row["state"],
                       snapshot=Snapshot.model_validate_json(row["snapshot_json"]),
                       created_at=row["created_at"], started_at=row["started_at"],
                       finished_at=row["finished_at"], epoch=row["epoch"], attempt=row["attempt"],
                       issue_code=row["issue_code"], resumed_at=row["resumed_at"])

    def get(self, run_id: str) -> RunView:
        with self.db.read() as conn:
            return self._view(conn.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone())

    def by_request(self, key: str) -> RunView:
        with self.db.read() as conn:
            return self._view(conn.execute("SELECT r.* FROM runs r JOIN run_requests q ON q.run_id=r.id WHERE q.request_key=?", (key,)).fetchone())

    def default_plan(self) -> tuple[int, DefaultPlan]:
        with self.db.read() as conn:
            row = conn.execute("SELECT * FROM settings WHERE id=1").fetchone()
            return row["revision"], DefaultPlan.model_validate_json(canonical(effective_browser_defaults(json.loads(row["plan_json"]))))

    def save_default(self, plan: DefaultPlan, expected_revision: int):
        # Revalidate even if a caller uses model_construct or mutates nested containers.
        plan = DefaultPlan.model_validate_json(plan.model_dump_json())
        with self.db.write() as conn:
            enabled = {r[0] for r in conn.execute("SELECT id FROM sites WHERE enabled=1")}
            if not set(plan.site_ids) <= enabled:
                raise ScoutError("SITE_DISABLED", "Plan contains unavailable sites", 422)
            self.validate_source_plan(plan)
            changed = conn.execute("UPDATE settings SET revision=revision+1,plan_json=? WHERE id=1 AND revision=?",
                                   (plan.model_dump_json(), expected_revision)).rowcount
            if not changed:
                raise ScoutError("REVISION_CONFLICT", "Default plan changed")
        return expected_revision + 1

    @staticmethod
    def validate_source_plan(plan):
        if plan.source_mode == "browser":
            if len(plan.site_ids) != 1 or plan.site_ids[0] not in BROWSER_SITES:
                raise ScoutError("BROWSER_SINGLE_SITE_REQUIRED", "Choose one registered browser site per Run", 422)
        elif any(s in BROWSER_SITES and s != "futario" for s in plan.site_ids):
            raise ScoutError("SOURCE_MODE_CONFLICT", "This site only supports normal-page browser acquisition", 422)

    def _event(self, conn, run_id: str, kind: str, epoch: int, detail: str = ""):
        conn.execute("INSERT INTO run_events(run_id,kind,at,epoch,detail) VALUES (?,?,?,?,?)",
                     (run_id, kind, timestamp(self.clock()), epoch, detail))

    def create(self, request: CreateRun) -> CreateResult:
        request = CreateRun.model_validate_json(request.model_dump_json(exclude_unset=True))
        payload = run_request_payload(request)
        fingerprint = digest(payload)
        with self.db.write() as conn:
            prior = conn.execute("SELECT * FROM run_requests WHERE request_key=?", (request.request_key,)).fetchone()
            if prior:
                if prior["payload_hash"] != fingerprint:
                    prior_run = self._view(conn.execute("SELECT * FROM runs WHERE id=?", (prior["run_id"],)).fetchone())
                    legacy = prior_run.snapshot.site_ids == ["futario"]
                    if not legacy or prior["payload_hash"] != digest(run_request_payload(request, legacy_browser=True)):
                        raise ScoutError("REQUEST_KEY_CONFLICT", "Same request key has different parameters")
                original = CreateResult.model_validate_json(prior["response_json"])
                return original.model_copy(update={"run": self._view(conn.execute("SELECT * FROM runs WHERE id=?", (prior["run_id"],)).fetchone()), "reused": True, "reuse_reason": "request_key"})
            active = conn.execute("SELECT * FROM runs WHERE state IN('queued','running','interrupted','cancelling')").fetchone()
            overrides = request.overrides.model_dump(exclude_unset=True)
            if active:
                if ("source_mode" in overrides and overrides["source_mode"] != self._view(active).snapshot.source_mode):
                    raise ScoutError("SOURCE_MODE_CONFLICT", "Active Run has a different frozen source mode")
                if (self._view(active).snapshot.source_mode == "browser" and "site_ids" in overrides
                        and overrides["site_ids"] != self._view(active).snapshot.site_ids):
                    raise ScoutError("SITE_SCOPE_CONFLICT", "Active browser Run belongs to a different frozen site")
                result = CreateResult(run=self._view(active), reused=True, reuse_reason="active_run",
                                      ignored_overrides=sorted(overrides))
            else:
                setting = conn.execute("SELECT * FROM settings WHERE id=1").fetchone()
                plan_data = effective_browser_defaults(json.loads(setting["plan_json"]))
                browser_mode = overrides.get("source_mode", plan_data.get("source_mode", "http")) == "browser"
                # Explicit browser site selection uses the verified registry. Old
                # saved single-site plans need no automatic settings mutation.
                if (not browser_mode and "site_ids" in overrides
                        and not set(overrides["site_ids"]) <= set(plan_data["site_ids"])):
                    raise ScoutError("INVALID_SCOPE", "Temporary sites must be a subset of the saved plan", 422)
                if "browser" in overrides:
                    overrides["browser"] = {**plan_data.get("browser", {}), **overrides["browser"]}
                plan_data.update(overrides)
                plan = DefaultPlan.model_validate_json(canonical(plan_data))
                sites = {row["id"]: row for row in conn.execute("SELECT * FROM sites WHERE enabled=1")}
                if not set(plan.site_ids) <= sites.keys():
                    raise ScoutError("SITE_DISABLED", "Plan contains unavailable sites", 422)
                self.validate_source_plan(plan)
                now = self.clock()
                snapshot = Snapshot(**plan.model_dump(), plan_revision=setting["revision"],
                                    window_start=timestamp(now - timedelta(days=plan.window_days).total_seconds()),
                                    window_end=timestamp(now),
                                    adapter_versions={s: (BROWSER_SITES[s].adapter_version if plan.source_mode == "browser" else sites[s]["adapter_version"]) for s in plan.site_ids},
                                    site_entries={s: (BROWSER_SITES[s].entry if plan.source_mode == "browser" else sites[s]["entry"]) for s in plan.site_ids},
                                    discovery_baseline_complete={s: bool(sites[s]["baseline_complete"]) for s in plan.site_ids})
                run_id = new_id()
                conn.execute("INSERT INTO runs(id,state,snapshot_json,created_at) VALUES (?,'queued',?,?)",
                             (run_id, snapshot.model_dump_json(), timestamp(now)))
                conn.execute("INSERT INTO run_seen_products SELECT ?,id FROM products", (run_id,))
                conn.execute("INSERT INTO run_attempts(run_id,number,started_at) VALUES (?,1,?)", (run_id, timestamp(now)))
                self._event(conn, run_id, "accepted", 0, request.trigger)
                result = CreateResult(run=self._view(conn.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone()),
                                      reused=False, reuse_reason=None, ignored_overrides=[])
            conn.execute("INSERT INTO run_requests VALUES (?,?,?,?)",
                         (request.request_key, fingerprint, result.run.id, result.model_dump_json()))
            return result

    def register_worker(self, owner: str, pid: int, born: float, executable: str):
        with self.db.write() as conn:
            conn.execute("INSERT INTO workers VALUES (?,?,?,?,?,'online')",
                         (owner, pid, born, executable, self.clock()))

    def worker_heartbeat(self, owner: str):
        with self.db.write() as conn:
            conn.execute("UPDATE workers SET heartbeat_at=? WHERE id=? AND state='online'", (self.clock(), owner))

    def claim(self, owner: str, lease_seconds: float = 60) -> Lease | None:
        if lease_seconds <= 0:
            raise ValueError("lease_seconds must be positive")
        with self.db.write() as conn:
            if not conn.execute("SELECT 1 FROM workers WHERE id=? AND state='online'", (owner,)).fetchone():
                raise ScoutError("WORKER_NOT_REGISTERED", "Worker is not registered")
            row = conn.execute("SELECT * FROM runs WHERE state='queued' ORDER BY created_at,id LIMIT 1").fetchone()
            if row is None:
                return None
            epoch = row["epoch"] + 1
            now = self.clock()
            conn.execute("UPDATE runs SET state='running',owner=?,epoch=?,lease_until=?,heartbeat_at=?,started_at=COALESCE(started_at,?) WHERE id=? AND state='queued'",
                         (owner, epoch, now + lease_seconds, now, timestamp(now), row["id"]))
            self._event(conn, row["id"], "claimed", epoch, owner)
            return Lease(run_id=row["id"], owner=owner, epoch=epoch)

    def fence(self, conn, lease: Lease):
        row = conn.execute("SELECT * FROM runs WHERE id=?", (lease.run_id,)).fetchone()
        if (row is None or row["owner"] != lease.owner or row["epoch"] != lease.epoch
                or row["state"] not in ("running", "cancelling")
                or row["lease_until"] is None or row["lease_until"] <= self.clock()):
            raise ScoutError("STALE_LEASE", "Worker lease is no longer valid")
        return row

    def heartbeat(self, lease: Lease, lease_seconds: float = 60):
        with self.db.write() as conn:
            self.fence(conn, lease)
            conn.execute("UPDATE runs SET heartbeat_at=?,lease_until=? WHERE id=?",
                         (self.clock(), self.clock() + lease_seconds, lease.run_id))

    def cancellation_requested(self, lease: Lease) -> bool:
        with self.db.read() as conn:
            return bool(self.fence(conn, lease)["cancel_requested"])

    def cancel(self, run_id: str, request_key: str):
        with self.db.write() as conn:
            if self._operation(conn, "cancel", run_id, request_key):
                return
            row = conn.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone()
            self._view(row)
            if row["state"] in ("queued", "interrupted"):
                conn.execute("UPDATE runs SET state='cancelled',cancel_requested=1,finished_at=?,epoch=epoch+1 WHERE id=?",
                             (timestamp(self.clock()), run_id))
                conn.execute("UPDATE run_attempts SET finished_at=?,result_state='cancelled' WHERE run_id=? AND number=?",
                             (timestamp(self.clock()), run_id, row["attempt"]))
                conn.execute("UPDATE work_items SET state='cancelled' WHERE run_id=? AND state!='completed'", (run_id,))
            elif row["state"] in ("running", "cancelling"):
                conn.execute("UPDATE runs SET state='cancelling',cancel_requested=1 WHERE id=?", (run_id,))
            self._event(conn, run_id, "cancel_requested", row["epoch"])

    def _operation(self, conn, verb: str, run_id: str, key: str) -> bool:
        if not key or len(key) > 128:
            raise ScoutError("INVALID_REQUEST_KEY", "Operation key must be 1..128 characters", 422)
        fingerprint = digest({"verb": verb, "run_id": run_id})
        prior = conn.execute("SELECT payload_hash FROM operation_requests WHERE key=?", (key,)).fetchone()
        if prior:
            if prior[0] != fingerprint:
                raise ScoutError("REQUEST_KEY_CONFLICT", "Operation key parameters differ")
            return True
        self._view(conn.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone())
        conn.execute("INSERT INTO operation_requests VALUES (?,?,?)", (key, fingerprint, run_id))
        return False

    def retry(self, run_id: str, request_key: str):
        with self.db.write() as conn:
            if self._operation(conn, "retry", run_id, request_key):
                return
            row = conn.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone()
            if row["state"] not in ("failed", "partial", "cancelled"):
                raise ScoutError("RETRY_NOT_ALLOWED", "Retry requires a failed, partial or cancelled run")
            if conn.execute("SELECT 1 FROM runs WHERE state IN('queued','running','interrupted','cancelling')").fetchone():
                raise ScoutError("ACTIVE_RUN", "Another run is active")
            self._requeue(conn, row, "manual_retry")

    def _requeue(self, conn, row, reason: str):
        now = timestamp(self.clock())
        conn.execute("UPDATE run_attempts SET finished_at=COALESCE(finished_at,?),result_state=COALESCE(result_state,?),reason=COALESCE(reason,?) WHERE run_id=? AND number=?",
                     (now, "interrupted" if reason == "recovered" else row["state"], reason, row["id"], row["attempt"]))
        conn.execute("UPDATE runs SET state='queued',owner=NULL,lease_until=NULL,epoch=epoch+1,attempt=attempt+1,cancel_requested=0,finished_at=NULL,issue_code=NULL,outcome_json=NULL,resumed_at=? WHERE id=?",
                     (now, row["id"]))
        conn.execute("INSERT INTO run_attempts(run_id,number,started_at,reason) VALUES (?,?,?,?)",
                     (row["id"], row["attempt"] + 1, now, reason))
        conn.execute("UPDATE work_attempts SET state='interrupted' WHERE state='running' AND item_id IN (SELECT id FROM work_items WHERE run_id=?)", (row["id"],))
        conn.execute("UPDATE work_items SET state='pending' WHERE run_id=? AND state!='completed'", (row["id"],))
        if self._view(row).snapshot.source_mode == "browser":
            conn.execute("UPDATE browser_sessions SET state='closed' WHERE run_id=?", (row["id"],))
            conn.execute("UPDATE browser_runs SET phase='waiting_host',source_wait=0,finish_received=0,last_activity=? WHERE run_id=?", (self.clock(), row["id"]))
            conn.execute("UPDATE browser_assets SET state='pending',issue_code=NULL WHERE run_id=? AND state='failed'", (row["id"],))
        self._event(conn, row["id"], reason, row["epoch"] + 1)

    def recover_expired(self, owner_is_dead: Callable[[dict], bool]) -> list[str]:
        # Liveness check outside transaction, then compare original epoch/owner and expiry.
        with self.db.read() as conn:
            candidates = [dict(row) for row in conn.execute(
                "SELECT r.*,w.pid,w.born,w.executable FROM runs r JOIN workers w ON w.id=r.owner "
                "WHERE r.state IN('running','interrupted','cancelling') AND r.lease_until<=?", (self.clock(),))]
        recovered = []
        for candidate in candidates:
            if not owner_is_dead(candidate):
                continue
            with self.db.write() as conn:
                row = conn.execute("SELECT * FROM runs WHERE id=?", (candidate["id"],)).fetchone()
                if (row["epoch"] != candidate["epoch"] or row["owner"] != candidate["owner"]
                        or row["state"] not in ("running", "interrupted", "cancelling")
                        or row["lease_until"] > self.clock()):
                    continue
                self._event(conn, row["id"], "interrupted", row["epoch"], "expired lease and confirmed dead process")
                if row["cancel_requested"]:
                    conn.execute("UPDATE runs SET state='cancelled',finished_at=?,epoch=epoch+1 WHERE id=?", (timestamp(self.clock()), row["id"]))
                    conn.execute("UPDATE run_attempts SET finished_at=?,result_state='cancelled' WHERE run_id=? AND number=?", (timestamp(self.clock()), row["id"], row["attempt"]))
                    conn.execute("UPDATE work_items SET state='cancelled' WHERE run_id=? AND state!='completed'", (row["id"],))
                else:
                    self._requeue(conn, row, "recovered")
                recovered.append(row["id"])
        return recovered

    def finish(self, lease: Lease, outcome: Outcome):
        outcome = Outcome.model_validate_json(outcome.model_dump_json())
        with self.db.write() as conn:
            row = self.fence(conn, lease)
            pending = conn.execute("SELECT COUNT(*) FROM work_items WHERE run_id=? AND state!='completed'", (lease.run_id,)).fetchone()[0]
            unresolved = conn.execute("SELECT COUNT(*) FROM archive_journal WHERE run_id=? AND state!='committed' AND recovery_state!='superseded'", (lease.run_id,)).fetchone()[0]
            if unresolved:
                outcome = outcome.model_copy(update={"state": "partial" if outcome.valid_results else "failed",
                    "required_complete": False, "issue_code": outcome.issue_code or "ARCHIVE_REPAIR_PENDING"})
            state = "cancelled" if row["cancel_requested"] else outcome.state
            if state == "succeeded" and (not outcome.coverage_complete or not outcome.required_complete or pending):
                raise ScoutError("INCOMPLETE_RUN", "Success requires complete coverage and all required work")
            if state == "partial" and outcome.valid_results == 0:
                raise ScoutError("NO_VALID_RESULTS", "Partial requires valid results")
            now = timestamp(self.clock())
            conn.execute("UPDATE runs SET state=?,finished_at=?,lease_until=NULL,issue_code=?,valid_results=?,outcome_json=? WHERE id=?",
                         (state, now, outcome.issue_code, outcome.valid_results, outcome.model_dump_json(), lease.run_id))
            conn.execute("UPDATE run_attempts SET finished_at=?,result_state=? WHERE run_id=? AND number=?", (now, state, lease.run_id, row["attempt"]))
            if state == "cancelled":
                conn.execute("UPDATE work_items SET state='cancelled' WHERE run_id=? AND state!='completed'", (lease.run_id,))
            conn.execute("UPDATE work_attempts SET state=? WHERE state='running' AND item_id IN (SELECT id FROM work_items WHERE run_id=?)", ("cancelled" if state == "cancelled" else "interrupted", lease.run_id))
            self._event(conn, lease.run_id, "finished", lease.epoch, state)

    def release(self, lease: Lease):
        with self.db.write() as conn:
            self.fence(conn, lease)
            conn.execute("UPDATE runs SET state='interrupted',lease_until=? WHERE id=?", (self.clock(), lease.run_id))
            self._event(conn, lease.run_id, "graceful_stop", lease.epoch)

    def stop_worker(self, owner: str):
        with self.db.write() as conn:
            conn.execute("UPDATE workers SET state='stopped' WHERE id=?", (owner,))

    def ensure_item(self, lease: Lease, key: str) -> str:
        with self.db.write() as conn:
            self.fence(conn, lease)
            row = conn.execute("SELECT id FROM work_items WHERE run_id=? AND item_key=?", (lease.run_id, key)).fetchone()
            if row:
                return row[0]
            item_id = new_id()
            conn.execute("INSERT INTO work_items(id,run_id,item_key,state) VALUES (?,?,?,'pending')", (item_id, lease.run_id, key))
            return item_id

    def start_item(self, lease: Lease, item_id: str) -> bool:
        with self.db.write() as conn:
            if self.fence(conn, lease)["cancel_requested"]:
                raise ScoutError("CANCEL_REQUESTED", "Do not start another item")
            row = conn.execute("SELECT * FROM work_items WHERE id=? AND run_id=?", (item_id, lease.run_id)).fetchone()
            if row is None:
                raise ScoutError("ITEM_NOT_FOUND", "Work item does not exist", 404)
            if row["state"] == "completed":
                return False
            if row["state"] != "pending":
                raise ScoutError("ITEM_NOT_PENDING", "Item must be requeued before another attempt")
            number = row["attempts"] + 1
            conn.execute("UPDATE work_items SET state='running',attempts=? WHERE id=?", (number, item_id))
            conn.execute("INSERT INTO work_attempts VALUES (?,?,?,'running',?)", (item_id, number, lease.epoch, timestamp(self.clock())))
            return True

    def complete_item(self, lease: Lease, item_id: str, output: dict):
        with self.db.write() as conn:
            row = conn.execute("SELECT state FROM work_items WHERE id=? AND run_id=?", (item_id, lease.run_id)).fetchone()
            if not row or row["state"] not in ("running", "completed"):
                raise ScoutError("ITEM_NOT_ACTIVE", "Completion requires a started work item")
            self._complete_item(conn, lease, item_id, output)

    def fail_item(self, lease: Lease, item_id: str, error_code: str):
        if not error_code or len(error_code) > 128:
            raise ScoutError("INVALID_ERROR_CODE", "Use a bounded error code, not raw source content", 422)
        with self.db.write() as conn:
            self.fence(conn, lease)
            changed = conn.execute("UPDATE work_items SET state='failed',error_code=? WHERE id=? AND run_id=? AND state='running'", (error_code, item_id, lease.run_id)).rowcount
            if not changed:
                raise ScoutError("ITEM_NOT_ACTIVE", "Failure requires a running work item")
            conn.execute("UPDATE work_attempts SET state='failed' WHERE item_id=? AND state='running'", (item_id,))

    def _complete_item(self, conn, lease: Lease, item_id: str, output: dict):
        self.fence(conn, lease)
        row = conn.execute("SELECT * FROM work_items WHERE id=? AND run_id=?", (item_id, lease.run_id)).fetchone()
        if row is None or row["state"] not in ("running", "completed", "pending"):
            raise ScoutError("ITEM_NOT_ACTIVE", "Work item is not active")
        if row["state"] == "completed":
            if row["output_json"] != canonical(output):
                raise ScoutError("ITEM_RESULT_CONFLICT", "Completed item cannot be replaced")
            return
        conn.execute("UPDATE work_items SET state='completed',output_json=?,error_code=NULL WHERE id=?", (canonical(output), item_id))
        conn.execute("UPDATE work_attempts SET state='completed' WHERE item_id=? AND number=? AND state='running'", (item_id, row["attempts"]))
