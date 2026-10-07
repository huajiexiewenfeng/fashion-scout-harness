import hashlib
import os
import sqlite3

import pytest

from fashion_scout.db.archive import Archive
from fashion_scout.domain import ScoutError


def staged(claimed):
    runs, paths, lease, run = claimed
    item = runs.ensure_item(lease, "image")
    runs.start_item(lease, item)
    payload = b"synthetic byte-level archive, not an image validation fixture"
    temp = paths.inside_media("temp/source.bin")
    temp.parent.mkdir(parents=True)
    temp.write_bytes(payload)
    archive = Archive(paths, runs)
    journal = archive.stage(lease, item, "temp/source.bin", "originals/source.bin",
                            hashlib.sha256(payload).hexdigest(), len(payload))
    return archive, journal, temp, paths.inside_media("originals/source.bin")


def test_recover_before_publish_and_idempotent_commit(claimed):
    archive, journal, temp, final = staged(claimed)
    lease = claimed[2]
    expected = temp.read_bytes()
    result = archive.recover(lease)
    assert result == {"recovered": [journal], "failures": [], "retryable": [], "blocked": [], "fatal_failures": []}
    asset = archive.commit(lease, journal)
    assert archive.commit(lease, journal) == asset
    assert final.read_bytes() == expected
    assert not temp.exists()
    with claimed[0].db.read() as conn:
        assert conn.execute("SELECT COUNT(*) FROM assets").fetchone()[0] == 1
        assert conn.execute("SELECT state FROM work_items").fetchone()[0] == "completed"


def test_crash_after_publish_before_transaction_recovers(claimed):
    archive, journal, temp, final = staged(claimed)
    final.parent.mkdir(parents=True)
    os.link(temp, final)  # Exact filesystem boundary left by a crash.
    asset = archive.commit(claimed[2], journal)
    with claimed[0].db.read() as conn:
        assert conn.execute("SELECT journal_id FROM assets WHERE id=?", (asset,)).fetchone()[0] == journal


def test_db_failure_rolls_back_metadata_then_recovers(claimed):
    archive, journal, temp, final = staged(claimed)
    runs = claimed[0]
    with runs.db.write() as conn:
        conn.execute("CREATE TRIGGER fail_work BEFORE UPDATE ON work_items BEGIN SELECT RAISE(ABORT,'injected disk/DB boundary'); END")
    with pytest.raises(sqlite3.IntegrityError):
        archive.commit(claimed[2], journal)
    assert final.is_file()
    assert temp.is_file()  # Publication alone must not delete bytes before DB commit.
    with runs.db.read() as conn:
        assert conn.execute("SELECT COUNT(*) FROM assets").fetchone()[0] == 0
        assert conn.execute("SELECT state FROM archive_journal").fetchone()[0] == "staged"
    with runs.db.write() as conn:
        conn.execute("DROP TRIGGER fail_work")
    assert archive.recover(claimed[2])["failures"] == []


def test_corrupt_destination_not_overwritten(claimed):
    archive, journal, temp, final = staged(claimed)
    final.parent.mkdir(parents=True)
    final.write_bytes(b"do not overwrite")
    result = archive.recover(claimed[2])
    assert result["failures"]
    assert final.read_bytes() == b"do not overwrite"
    with claimed[0].db.read() as conn:
        assert conn.execute("SELECT COUNT(*) FROM assets").fetchone()[0] == 0
        assert conn.execute("SELECT state FROM archive_journal").fetchone()[0] == "failed"


def test_paths_cannot_escape(claimed):
    paths = claimed[1]
    with pytest.raises(ScoutError) as error:
        paths.inside_media("../outside")
    assert error.value.code == "INVALID_PATH"


def test_old_epoch_cannot_adopt_published_file(claimed):
    archive, journal, temp, final = staged(claimed)
    with claimed[0].db.write() as conn:
        conn.execute("UPDATE runs SET epoch=epoch+1 WHERE id=?", (claimed[2].run_id,))
    with pytest.raises(ScoutError) as error:
        archive.commit(claimed[2], journal)
    assert error.value.code == "STALE_LEASE"
    assert not final.exists()


def test_epoch_changes_during_publish_cannot_delete_temp(claimed, monkeypatch):
    archive, journal, temp, final = staged(claimed)
    verify = archive.verify
    def change_owner(path, sha, size):
        verify(path, sha, size)
        if path == final:
            with claimed[0].db.write() as conn:
                conn.execute("UPDATE runs SET epoch=epoch+1 WHERE id=?", (claimed[2].run_id,))
    monkeypatch.setattr(archive, "verify", change_owner)
    with pytest.raises(ScoutError) as error:
        archive.commit(claimed[2], journal)
    assert error.value.code == "STALE_LEASE"
    assert temp.exists() and final.exists()
    assert temp.read_bytes() == final.read_bytes()
