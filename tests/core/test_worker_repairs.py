"""Actual Worker + SQLite + files; injected executor replaces only absent T2 networking."""
import hashlib
import sqlite3

import pytest

from fashion_scout.db.archive import Archive
from fashion_scout.domain import Outcome, ScoutError
from fashion_scout.worker import Worker


def outcome(count=0, state="succeeded"):
    return Outcome(state=state, valid_results=count, coverage_complete=True,
                   required_complete=True, evidence_ref="test:synthetic-executor")


def put(archive, lease, item, name, data=b"synthetic"):
    temp = archive.paths.inside_media("temp/" + name)
    temp.parent.mkdir(parents=True, exist_ok=True)
    temp.write_bytes(data)
    journal = archive.stage(lease, item, "temp/" + name, "originals/" + name,
                            hashlib.sha256(data).hexdigest(), len(data))
    return journal, temp


def seed(claimed):
    runs, paths, lease, run = claimed
    archive = Archive(paths, runs)
    done = runs.ensure_item(lease, "already-done")
    runs.start_item(lease, done)
    journal, _ = put(archive, lease, done, "retained.bin")
    asset = archive.commit(lease, journal)
    bad = runs.ensure_item(lease, "bad")
    runs.start_item(lease, bad)
    journal, temp = put(archive, lease, bad, "bad.bin")
    good = runs.ensure_item(lease, "good")
    with runs.db.write() as conn:
        conn.execute("INSERT INTO products(id,site_id,source_id,first_seen_at) VALUES ('p','futario','1','now')")
        conn.execute("INSERT INTO product_user_state(product_id,favorite,category_override,viewed_at) VALUES ('p',1,'manual','viewed')")
    runs.finish(lease, outcome(state="failed"))
    return archive, bad, good, done, journal, temp, asset


def execute(runs, paths, run_id, executor, key="retry"):
    runs.retry(run_id, key)
    Worker(paths, lambda: runs.get(run_id).state in ("succeeded", "failed", "partial", "cancelled"),
           executor=executor, heartbeat_seconds=0.1, lease_seconds=10).run()
    return runs.get(run_id)


@pytest.mark.parametrize("damage", ["missing", "corrupt"])
@pytest.mark.parametrize("new_bytes", [b"synthetic", b"changed source bytes"])
def test_worker_repairs_unpublished_item_and_preserves_other_results(claimed, damage, new_bytes):
    runs, paths, old, run = claimed
    archive, bad, good, done, journal, temp, asset = seed(claimed)
    if damage == "missing":
        temp.unlink()
    else:
        temp.write_bytes(b"corrupted")  # Same size; exercise hash mismatch, not just size.
    calls = []

    def executor(ctx):
        calls.append(ctx.lease)
        recovery = ctx.archive_recovery
        assert [x["item_id"] for x in recovery["retryable"]] == [bad]
        assert not recovery["fatal_failures"]
        # Repeated recovery is durable/idempotent, no lost item or duplicated issue.
        assert archive.recover(ctx.lease)["retryable"] == recovery["retryable"]
        assert not runs.start_item(ctx.lease, done)
        assert runs.start_item(ctx.lease, good)
        normal, _ = put(archive, ctx.lease, good, "good.bin")
        archive.commit(ctx.lease, normal)
        assert runs.start_item(ctx.lease, bad)
        with pytest.raises(ScoutError) as error:
            archive.commit(old, journal)
        assert error.value.code == "STALE_LEASE"
        with pytest.raises(ScoutError) as error:
            put(archive, old, bad, "repaired.bin", new_bytes)
        assert error.value.code == "STALE_LEASE"
        replacement, _ = put(archive, ctx.lease, bad, "repaired.bin", new_bytes)
        assert put(archive, ctx.lease, bad, "repaired.bin", new_bytes)[0] == replacement
        repaired_asset = archive.commit(ctx.lease, replacement)
        assert archive.commit(ctx.lease, replacement) == repaired_asset
        assert not archive.recover(ctx.lease)["failures"]
        if replacement != journal:
            with pytest.raises(ScoutError) as error:
                archive.commit(ctx.lease, journal)
            assert error.value.code == "JOURNAL_SUPERSEDED"
        return outcome(3)

    result = execute(runs, paths, run.id, executor)
    assert len(calls) == 1 and result.id == run.id and result.attempt == 2
    assert result.state == "succeeded" and result.snapshot == run.snapshot
    assert calls[0].epoch > old.epoch
    assert paths.inside_media("originals/repaired.bin").read_bytes() == new_bytes
    with runs.db.read() as conn:
        assert conn.execute("SELECT COUNT(*) FROM assets").fetchone()[0] == 3
        assert conn.execute("SELECT id FROM assets WHERE id=?", (asset,)).fetchone()[0] == asset
        assert conn.execute("SELECT attempts FROM work_items WHERE id=?", (done,)).fetchone()[0] == 1
        assert conn.execute("SELECT favorite,category_override,viewed_at FROM product_user_state").fetchone()[:] == (1, "manual", "viewed")
        assert conn.execute("SELECT COUNT(*) FROM archive_journal_events WHERE journal_id=? AND kind='retryable'", (journal,)).fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM archive_journal_events WHERE journal_id=? AND kind='superseded'", (journal,)).fetchone()[0] == 1
        assert [x[0] for x in conn.execute("SELECT state FROM work_attempts WHERE item_id=? ORDER BY number", (bad,))] == ["interrupted", "completed"]


@pytest.mark.parametrize("count,expected", [(0, "failed"), (1, "partial")])
def test_unresolved_item_does_not_block_executor_or_allow_false_success(claimed, count, expected):
    runs, paths, _, run = claimed
    archive, bad, good, _, journal, temp, _ = seed(claimed)
    temp.unlink()
    calls = []

    def executor(ctx):
        calls.append(ctx.lease)
        assert ctx.archive_recovery["retryable"][0]["item_id"] == bad
        if count and runs.start_item(ctx.lease, good):
            normal, _ = put(archive, ctx.lease, good, "good.bin")
            archive.commit(ctx.lease, normal)
        # Even an incorrect complete report cannot omit the unresolved journal.
        return outcome(count)

    for index in range(2):
        result = execute(runs, paths, run.id, executor, "retry-" + str(index))
        assert result.state == expected
        assert result.issue_code == "ARCHIVE_REPAIR_PENDING"
    assert len(calls) == 2
    with runs.db.read() as conn:
        assert conn.execute("SELECT state,recovery_state,error_code FROM archive_journal WHERE id=?", (journal,)).fetchone()[:] == ("failed", "retryable", "ARCHIVE_STAGING_UNAVAILABLE")
        saved = conn.execute("SELECT outcome_json FROM runs WHERE id=?", (run.id,)).fetchone()[0]
        assert not Outcome.model_validate_json(saved).required_complete


def test_immutable_target_conflict_is_local_and_cannot_be_restaged(claimed):
    runs, paths, _, run = claimed
    archive, bad, good, _, journal, _, _ = seed(claimed)
    final = paths.inside_media("originals/bad.bin")
    final.write_bytes(b"immutable conflicting bytes")

    def executor(ctx):
        blocked = ctx.archive_recovery["blocked"]
        assert blocked[0]["item_id"] == bad and blocked[0]["scope"] == "item"
        assert blocked[0]["code"] == "ARCHIVE_TARGET_CONFLICT"
        assert blocked[0]["evidence_ref"] == "archive_journal:" + journal
        assert not ctx.archive_recovery["fatal_failures"]
        # Force a caller's attempt to bypass the blocked item: the journal still fences stage.
        with runs.db.write() as conn:
            conn.execute("UPDATE work_items SET state='pending' WHERE id=?", (bad,))
        runs.start_item(ctx.lease, bad)
        with pytest.raises(ScoutError) as error:
            put(archive, ctx.lease, bad, "alternative.bin")
        assert error.value.code == "JOURNAL_CONFLICT"
        runs.start_item(ctx.lease, good)
        normal, _ = put(archive, ctx.lease, good, "good.bin")
        archive.commit(ctx.lease, normal)
        return outcome(2)

    result = execute(runs, paths, run.id, executor)
    assert result.state == "partial"
    assert final.read_bytes() == b"immutable conflicting bytes"
    assert not paths.inside_media("originals/alternative.bin").exists()
    with runs.db.read() as conn:
        assert conn.execute("SELECT recovery_state FROM archive_journal WHERE id=?", (journal,)).fetchone()[0] == "blocked"
        assert conn.execute("SELECT COUNT(*) FROM archive_journal_events WHERE code='ARCHIVE_TARGET_CONFLICT'").fetchone()[0] == 1


def test_storage_root_mismatch_stops_before_executor(claimed):
    runs, paths, _, run = claimed
    _, _, _, _, journal, _, _ = seed(claimed)
    with runs.db.write() as conn:
        conn.execute("INSERT INTO storage_roots VALUES ('other','C:/not-the-active-root','media')")
        conn.execute("UPDATE archive_journal SET root_id='other' WHERE id=?", (journal,))
    calls = []
    result = execute(runs, paths, run.id, lambda ctx: calls.append(ctx))
    assert calls == [] and result.state == "failed"
    assert result.issue_code == "ARCHIVE_RECOVERY_REQUIRED"
    with runs.db.read() as conn:
        assert conn.execute("SELECT error_code FROM archive_journal WHERE id=?", (journal,)).fetchone()[0] == "ARCHIVE_ROOT_MISMATCH"


def test_permission_failure_is_environment_blocker(claimed, monkeypatch):
    from pathlib import Path
    runs, paths, _, run = claimed
    _, _, _, _, journal, temp, _ = seed(claimed)
    real_open = Path.open

    def denied(path, *args, **kwargs):
        if path == temp:
            raise PermissionError("injected permission fault")
        return real_open(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", denied)
    calls = []
    result = execute(runs, paths, run.id, lambda ctx: calls.append(ctx))
    assert calls == [] and result.state == "failed"
    assert result.issue_code == "ARCHIVE_RECOVERY_REQUIRED"
    with runs.db.read() as conn:
        assert conn.execute("SELECT recovery_state,error_code FROM archive_journal WHERE id=?", (journal,)).fetchone()[:] == ("blocked", "ARCHIVE_IO_ERROR")
        assert '"scope":"run"' in conn.execute("SELECT detail_json FROM archive_journal_events WHERE journal_id=?", (journal,)).fetchone()[0]


def test_migration_from_v2_preserves_journal_and_checksums(tmp_path):
    from pathlib import Path
    from fashion_scout.db import Database
    import fashion_scout.db.store
    db = Database(tmp_path / "upgrade.sqlite3")
    migrations = Path(fashion_scout.db.store.__file__).parent / "migrations"
    with db.read() as conn:
        conn.execute("CREATE TABLE schema_migrations(version INTEGER PRIMARY KEY,sha256 TEXT NOT NULL)")
        for version, name in [(1, "001_core.sql"), (2, "002_catalog_contract.sql")]:
            source = (migrations / name).read_text("utf-8")
            conn.executescript(source)
            conn.execute("INSERT INTO schema_migrations VALUES (?,?)", (version, hashlib.sha256(source.encode()).hexdigest()))
        conn.execute("INSERT INTO runs(id,state,snapshot_json,created_at) VALUES ('old','failed','{}','then')")
        conn.execute("INSERT INTO work_items(id,run_id,item_key,state) VALUES ('item','old','image','pending')")
        conn.execute("INSERT INTO storage_roots VALUES ('root','C:/media','media')")
        conn.execute("INSERT INTO archive_journal VALUES ('journal','old','item',1,'root','temp/a','originals/a',?,1,'failed','OLD_FAILURE')", ("0" * 64,))
        before = [tuple(row) for row in conn.execute("SELECT * FROM schema_migrations ORDER BY version")]
    db.initialize()
    db.initialize()
    with db.read() as conn:
        assert [tuple(row) for row in conn.execute("SELECT * FROM schema_migrations WHERE version<3 ORDER BY version")] == before
        assert conn.execute("SELECT state,error_code,recovery_state,generation FROM archive_journal").fetchone()[:] == ("failed", "OLD_FAILURE", "active", 0)
        assert conn.execute("SELECT COUNT(*) FROM schema_migrations").fetchone()[0] == 10


def test_repair_db_failure_rolls_back_and_remains_recoverable(claimed):
    runs, paths, _, run = claimed
    archive, bad, _, _, journal, temp, _ = seed(claimed)
    temp.unlink()

    def executor(ctx):
        runs.start_item(ctx.lease, bad)
        with runs.db.write() as conn:
            conn.execute("CREATE TRIGGER deny_restage BEFORE UPDATE ON archive_journal WHEN NEW.state='staged' BEGIN SELECT RAISE(ABORT,'test repair failure'); END")
        with pytest.raises(sqlite3.IntegrityError):
            put(archive, ctx.lease, bad, "repair.bin")
        with runs.db.write() as conn:
            assert conn.execute("SELECT recovery_state,generation FROM archive_journal WHERE id=?", (journal,)).fetchone()[:] == ("retryable", 0)
            assert conn.execute("SELECT COUNT(*) FROM archive_journal_events WHERE kind='superseded'").fetchone()[0] == 0
            conn.execute("DROP TRIGGER deny_restage")
        repaired, _ = put(archive, ctx.lease, bad, "repair.bin")
        archive.commit(ctx.lease, repaired)
        # Good is still pending; this example explicitly reports partial coverage.
        return outcome(2, "partial")

    assert execute(runs, paths, run.id, executor).state == "partial"
