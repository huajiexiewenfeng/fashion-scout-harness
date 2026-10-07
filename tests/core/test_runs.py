from concurrent.futures import ThreadPoolExecutor
import json
import sqlite3
import time

import pytest
from pydantic import ValidationError

from fashion_scout.db import Database
from fashion_scout.domain import CreateRun, DefaultPlan, Outcome, ScoutError
from fashion_scout.domain.models import Overrides
from fashion_scout.processes import identity, is_dead
from fashion_scout.services.runs import Runs

FAILED = Outcome(state="failed", valid_results=0, coverage_complete=False,
                 required_complete=False, evidence_ref="test:failure", issue_code="TEST_FAILURE")


def test_environment_and_migrations(service, monkeypatch):
    from fashion_scout.db.store import environment_check
    runs, paths = service
    with runs.db.read() as conn:
        assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
        assert conn.execute("PRAGMA synchronous").fetchone()[0] == 2
        assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        assert conn.execute("PRAGMA busy_timeout").fetchone()[0] == 5000
        assert conn.execute("SELECT COUNT(*) FROM schema_migrations").fetchone()[0] == 10
    runs.initialize()  # No duplicate defaults or schema.
    monkeypatch.setattr(sqlite3, "sqlite_version_info", (3, 51, 2))
    with pytest.raises(ScoutError, match="SQLite"):
        environment_check()


def test_migration_tampering_rejected(service):
    runs, _ = service
    with runs.db.write() as conn:
        conn.execute("UPDATE schema_migrations SET sha256='changed' WHERE version=1")
    with pytest.raises(ScoutError) as error:
        runs.initialize()
    assert error.value.code == "MIGRATION_CHANGED"


@pytest.mark.parametrize("value", [
    {"request_key": "x", "trigger": "skill", "overrides": {"window_days": True}},
    {"request_key": "x", "trigger": "skill", "overrides": {"window_days": None}},
    {"request_key": "x", "trigger": "skill", "unexpected": 1},
    {"request_key": "x", "trigger": "skill", "overrides": {"site_ids": []}},
])
def test_strict_input(value):
    with pytest.raises(ValidationError):
        CreateRun.model_validate(value)


def test_snapshot_default_cas_and_replay_terminal(service):
    runs, _ = service
    request = CreateRun(request_key="original", trigger="skill", overrides=Overrides(window_days=7))
    accepted = runs.create(request)
    assert accepted.run.snapshot.window_days == 7
    revision, saved = runs.default_plan()
    assert saved.window_days == 14
    runs.save_default(saved.model_copy(update={"unknown_date_policy": "exclude"}), revision)
    assert runs.get(accepted.run.id).snapshot.unknown_date_policy == "include"
    with pytest.raises(ScoutError) as error:
        runs.save_default(saved, revision)
    assert error.value.code == "REVISION_CONFLICT"
    active = runs.create(CreateRun(request_key="next", trigger="ui", overrides=Overrides(window_days=14)))
    assert active.run.id == accepted.run.id
    assert active.ignored_overrides == ["window_days"]
    assert active.run.snapshot.window_days == 7
    with pytest.raises(ScoutError) as error:
        runs.create(CreateRun(request_key="original", trigger="skill"))
    assert error.value.code == "REQUEST_KEY_CONFLICT"
    runs.cancel(accepted.run.id, "cancel")
    replay = runs.create(request)
    assert replay.reused and replay.run.id == accepted.run.id and replay.run.state == "cancelled"
    assert runs.by_request("next").id == accepted.run.id
    # New key after terminal creates genuinely new work; no automatic launch.
    assert runs.create(CreateRun(request_key="new", trigger="ui")).run.id != accepted.run.id


def test_concurrent_requests_and_claims(service):
    runs, _ = service
    def create(index):
        return runs.create(CreateRun(request_key=f"request-{index}", trigger="skill"))
    with ThreadPoolExecutor(max_workers=12) as pool:
        results = list(pool.map(create, range(24)))
    assert len({r.run.id for r in results}) == 1
    assert sum(not r.reused for r in results) == 1
    who = identity()
    for index in range(12):
        runs.register_worker(str(index), who["pid"], who["born"], who["executable"])
    with ThreadPoolExecutor(max_workers=12) as pool:
        leases = list(pool.map(lambda i: runs.claim(str(i)), range(12)))
    assert sum(x is not None for x in leases) == 1
    # Schema, independently of service logic, rejects a second active run.
    with runs.db.write() as conn:
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("INSERT INTO runs(id,state,snapshot_json,created_at) VALUES ('illegal','queued','{}','now')")


def test_busy_is_bounded_and_no_partial_request(service):
    runs, paths = service
    short = Runs(Database(paths.db, busy_ms=20, attempts=2))
    with runs.db.write():
        start = time.monotonic()
        with pytest.raises(ScoutError) as error:
            short.create(CreateRun(request_key="busy", trigger="skill"))
        assert error.value.code == "DATABASE_BUSY"
        assert time.monotonic() - start < 1
    with runs.db.read() as conn:
        assert conn.execute("SELECT COUNT(*) FROM run_requests").fetchone()[0] == 0


def test_cancel_retry_preserves_completed_and_human_state(claimed):
    runs, _, lease, run = claimed
    done = runs.ensure_item(lease, "done")
    pending = runs.ensure_item(lease, "pending")
    runs.start_item(lease, done)
    runs.complete_item(lease, done, {"value": 1})
    with runs.db.write() as conn:
        conn.execute("INSERT INTO products(id,site_id,source_id,first_seen_at) VALUES ('p','futario','1','now')")
        conn.execute("INSERT INTO product_user_state(product_id,favorite,category_override,viewed_at) VALUES ('p',1,'manual','viewed')")
    runs.cancel(run.id, "cancel-1")
    with pytest.raises(ScoutError) as error:
        runs.start_item(lease, pending)
    assert error.value.code == "CANCEL_REQUESTED"
    runs.finish(lease, FAILED)
    assert runs.get(run.id).state == "cancelled"
    runs.retry(run.id, "retry-1")
    runs.retry(run.id, "retry-1")
    second = runs.claim("one")
    assert second.run_id == run.id and second.epoch > lease.epoch
    assert not runs.start_item(second, done)
    assert runs.start_item(second, pending)
    with runs.db.read() as conn:
        assert conn.execute("SELECT favorite,category_override,viewed_at FROM product_user_state").fetchone()[:] == (1, "manual", "viewed")
        assert conn.execute("SELECT COUNT(*) FROM run_attempts").fetchone()[0] == 2
        assert conn.execute("SELECT attempts FROM work_items WHERE id=?", (done,)).fetchone()[0] == 1
    with pytest.raises(ScoutError) as error:
        runs.finish(lease, FAILED)
    assert error.value.code == "STALE_LEASE"


def test_expiry_alone_cannot_steal_live_worker(claimed):
    runs, _, lease, run = claimed
    base = runs.clock()
    runs.clock = lambda: base + 120
    assert runs.recover_expired(is_dead) == []
    with pytest.raises(ScoutError) as error:
        runs.heartbeat(lease)
    assert error.value.code == "STALE_LEASE"
    assert runs.get(run.id).epoch == lease.epoch


def test_failed_run_retry_reuses_completed_results(claimed):
    runs, _, lease, run = claimed
    item = runs.ensure_item(lease, "complete")
    runs.start_item(lease, item)
    runs.complete_item(lease, item, {"result": "retained"})
    runs.finish(lease, FAILED)
    runs.retry(run.id, "retry")
    next_lease = runs.claim("one")
    assert runs.ensure_item(next_lease, "complete") == item
    assert not runs.start_item(next_lease, item)
    assert runs.get(run.id).attempt == 2
    assert runs.get(run.id).snapshot == run.snapshot


def test_success_requires_complete_work_and_coverage(claimed):
    runs, _, lease, _ = claimed
    runs.ensure_item(lease, "not-done")
    with pytest.raises(ScoutError) as error:
        runs.finish(lease, Outcome(state="succeeded", valid_results=1, coverage_complete=True,
                                  required_complete=True, evidence_ref="test"))
    assert error.value.code == "INCOMPLETE_RUN"
    assert runs.get(lease.run_id).state == "running"


def test_production_executor_cannot_report_empty_success(claimed):
    from fashion_scout.worker import unavailable_executor
    class Check:
        def checkpoint(self):
            pass
    with pytest.raises(ScoutError) as error:
        unavailable_executor(Check())
    assert error.value.code == "ADAPTER_NOT_IMPLEMENTED"


def test_failed_item_history_and_unstarted_completion(claimed):
    runs, _, lease, run = claimed
    item = runs.ensure_item(lease, "will-fail")
    with pytest.raises(ScoutError):
        runs.complete_item(lease, item, {})
    runs.start_item(lease, item)
    runs.fail_item(lease, item, "TEST_NETWORK")
    runs.finish(lease, FAILED)
    runs.retry(run.id, "again")
    second = runs.claim("one")
    runs.start_item(second, item)
    runs.complete_item(second, item, {"ok": True})
    with runs.db.read() as conn:
        assert [r[0] for r in conn.execute("SELECT state FROM work_attempts ORDER BY number")] == ["failed", "completed"]
