"""Manager R1-R3 regressions using the production Worker, DB and actual files."""
import hashlib
import time
import pytest

from fashion_scout.db.archive import Archive
from fashion_scout.domain import ScoutError
from fashion_scout.services.catalog import product_detail
from tests.t2_helpers import setup, accept, execute, Scenario, product, png


def test_late_same_run_retry_has_active_time_but_keeps_cumulative_budgets(tmp_path):
    runs, paths = setup(tmp_path)
    scenario = Scenario([product(images=2)])
    scenario.image_data["/1-1.png"] = b"bad"
    run = accept(runs)
    assert execute(runs, paths, run.id, scenario).state == "partial"
    with runs.db.write() as conn:
        old = dict(conn.execute("SELECT * FROM collection_runs").fetchone())
        conn.execute("UPDATE collection_runs SET started_at=?", (time.time()-7200,))
    before = len(scenario.calls)
    scenario.image_data["/1-1.png"] = png("blue")
    runs.retry(run.id, "late-repair")
    assert execute(runs, paths, run.id, scenario).state == "succeeded"
    assert len(scenario.calls) == before+1
    with runs.db.read() as conn:
        now = conn.execute("SELECT * FROM collection_runs").fetchone()
        assert now["request_count"] == old["request_count"]+1
        assert now["image_requests"] == old["image_requests"]+1
        assert now["downloaded_bytes"] == old["downloaded_bytes"]+len(png("blue"))
        assert now["started_at"] < time.time()-7100
        assert conn.execute("SELECT COUNT(*) FROM run_attempts").fetchone()[0] == 2


def test_active_time_still_stops_execution_and_explicit_retry_resumes(tmp_path):
    runs, paths = setup(tmp_path)
    scenario = Scenario([product()])
    run = accept(runs)
    def expire(ctx):
        ctx.collection_started -= 7200
    assert execute(runs, paths, run.id, scenario, before=expire).state == "failed"
    assert scenario.calls == []
    with runs.db.read() as conn:
        assert conn.execute("SELECT code FROM issues").fetchone()[0] == "RUN_TIME_BUDGET"
    runs.retry(run.id, "fresh-execution")
    assert execute(runs, paths, run.id, scenario).state == "succeeded"


def test_old_run_waits_for_persisted_cooldown_then_repairs_same_run(tmp_path):
    runs, paths = setup(tmp_path)
    run, scenario = accept(runs), Scenario([product(images=2)])
    scenario.image_data["/1-1.png"] = b"bad"
    assert execute(runs, paths, run.id, scenario).state == "partial"
    count = len(scenario.calls)
    with runs.db.write() as conn:
        conn.execute("UPDATE collection_runs SET started_at=?", (time.time()-7200,))
        conn.execute("INSERT INTO network_throttle VALUES ('futario',?,'server',NULL,?)", (time.time()+600, time.time()))
    scenario.image_data["/1-1.png"] = png("blue")
    runs.retry(run.id, "during-cooldown")
    assert execute(runs, paths, run.id, scenario).state == "partial"
    assert len(scenario.calls) == count
    with runs.db.write() as conn:
        conn.execute("UPDATE network_throttle SET not_before=?", (time.time()-1,))
    runs.retry(run.id, "after-cooldown")
    assert execute(runs, paths, run.id, scenario).state == "succeeded"
    assert len(scenario.calls) == count+1


def test_active_time_is_checked_after_receiving_bytes(tmp_path):
    runs, paths = setup(tmp_path)
    run, scenario = accept(runs), Scenario([product()])
    from unittest.mock import patch
    from fashion_scout.services.catalog import Catalog
    original = Catalog.bytes_charge
    def byte_charge(catalog, size):
        catalog.execution_started -= 7200
        return original(catalog, size)
    with patch.object(Catalog, "bytes_charge", byte_charge):
        assert execute(runs, paths, run.id, scenario).state == "failed"
    assert len(scenario.calls) == 1
    with runs.db.read() as conn:
        assert conn.execute("SELECT downloaded_bytes FROM collection_runs").fetchone()[0] > 0
        assert conn.execute("SELECT code FROM issues").fetchone()[0] == "RUN_TIME_BUDGET"


def test_exhausted_cumulative_budget_is_not_reset_or_reported_retryable(tmp_path):
    from fashion_scout.domain.models import Network
    runs, paths = setup(tmp_path, network=Network(min_interval_ms=1, max_http_requests=3))
    run, scenario = accept(runs), Scenario([product()])
    assert execute(runs, paths, run.id, scenario).state == "failed"
    runs.retry(run.id, "cannot-reset-budget")
    assert execute(runs, paths, run.id, scenario).state == "failed"
    assert len(scenario.calls) == 3
    with runs.db.read() as conn:
        issue = conn.execute("SELECT * FROM issues WHERE code='REQUEST_BUDGET'").fetchone()
        assert issue["retryable"] == 0
        assert "same_run_limits_do_not_reset" in issue["evidence_ref"]


@pytest.mark.parametrize("repair", ["remove_missing", "duplicate_bytes", "different_bytes"])
def test_coverage_revision_is_separate_from_material_hash_set(tmp_path, repair):
    runs, paths = setup(tmp_path)
    item = product(images=2)
    scenario = Scenario([item])
    scenario.image_data["/1-1.png"] = b"bad"
    first = accept(runs)
    assert execute(runs, paths, first.id, scenario).state == "partial"
    before = product_detail(runs.db, "futario-1")
    frozen = before["versions"]
    if repair == "remove_missing":
        item["images"].pop()
        second = accept(runs, "source-removed-missing")
    else:
        scenario.image_data["/1-1.png"] = png("blue" if repair == "different_bytes" else "red")
        runs.retry(first.id, "repair")
        second = first
    assert execute(runs, paths, second.id, scenario).state == "succeeded"
    after = product_detail(runs.db, "futario-1")
    assert all(v in after["versions"] for v in frozen)
    assert after["current_gallery"]["missing_ids"] == []
    if repair == "different_bytes":
        assert before["latest_available_version_id"] != after["latest_available_version_id"]
    else:
        assert before["latest_available_version_id"] == after["latest_available_version_id"]
        assert after["latest_available_revision"] == before["latest_available_revision"]+1
    assert after["latest_complete_version_id"] == after["latest_observed_version_id"] == after["latest_available_version_id"]


def test_repeated_identical_downloads_and_invalid_bytes_leave_no_owned_parts(tmp_path):
    runs, paths = setup(tmp_path)
    scenario = Scenario([product(images=3)])
    for number in range(3):
        run = accept(runs, str(number))
        assert execute(runs, paths, run.id, scenario).state == "succeeded"
        assert list(paths.media.rglob("*.part")) == []
    original = next((paths.media/"originals").rglob("*.png"))
    assert hashlib.sha256(original.read_bytes()).hexdigest() == hashlib.sha256(png()).hexdigest()
    unrelated = paths.media/"temp"/"unrelated.part"
    unrelated.write_bytes(b"not owned")
    scenario.image_data["/1-0.png"] = b"invalid image"
    run = accept(runs, "invalid")
    assert execute(runs, paths, run.id, scenario).state == "partial"
    assert list(paths.media.rglob("*.part")) == [unrelated]
    assert original.read_bytes() == png()


def test_only_adding_missing_image_changes_manifest_not_content(tmp_path):
    runs, paths = setup(tmp_path)
    item = product(images=1)
    scenario = Scenario([item])
    first = accept(runs)
    assert execute(runs, paths, first.id, scenario).state == "succeeded"
    old = product_detail(runs.db, "futario-1")
    item["images"] = product(images=2)["images"]
    scenario.image_data["/1-1.png"] = b"bad"
    second = accept(runs, "new-missing-image")
    assert execute(runs, paths, second.id, scenario).state == "partial"
    now = product_detail(runs.db, "futario-1")
    assert now["latest_available_version_id"] == old["latest_available_version_id"]
    assert now["latest_observed_revision"] == old["latest_observed_revision"]+1
    assert now["latest_complete_revision"] == old["latest_complete_revision"]
    assert now["current_gallery"]["content_digest"] == old["current_gallery"]["content_digest"]
    assert len(now["current_gallery"]["missing_ids"]) == 1
    assert all(v in now["versions"] for v in old["versions"])


def test_crash_after_commit_before_cleanup_is_recovered_without_redownload(tmp_path, monkeypatch):
    runs, paths = setup(tmp_path)
    run, scenario = accept(runs), Scenario([product()])
    cleanup, committed = Archive.cleanup_temp, Archive.cleanup_committed
    monkeypatch.setattr(Archive, "cleanup_temp", lambda *args: None)
    def crash(*args):
        raise RuntimeError("process loss after DB commit before temp cleanup")
    monkeypatch.setattr(Archive, "cleanup_committed", crash)
    with pytest.raises(RuntimeError):
        execute(runs, paths, run.id, scenario)
    assert len(list(paths.media.rglob("*.part"))) == 1
    monkeypatch.setattr(Archive, "cleanup_temp", cleanup)
    monkeypatch.setattr(Archive, "cleanup_committed", committed)
    runs.retry(run.id, "recover-cleanup")
    assert execute(runs, paths, run.id, scenario).state == "succeeded"
    assert list(paths.media.rglob("*.part")) == []
    assert sum("cdn.shopify.com" in u for u in scenario.calls) == 1


def test_temp_cleanup_fences_stale_owner_and_preserves_replaced_identity(tmp_path):
    from fashion_scout.processes import identity
    runs, paths = setup(tmp_path)
    accept(runs)
    who = identity()
    runs.register_worker("one", who["pid"], who["born"], who["executable"])
    lease = runs.claim("one")
    archive = Archive(paths, runs)
    item = runs.ensure_item(lease, "temp-test")
    relative = archive.create_temp(lease, item)
    path = paths.inside_media(relative)
    # Keep the old inode allocated to avoid filesystem inode reuse in this test.
    path.rename(path.with_suffix(".preserved"))
    path.write_bytes(b"replacement owned elsewhere")
    archive.cleanup_temp(lease, relative)
    assert path.read_bytes() == b"replacement owned elsewhere"
    with runs.db.write() as conn:
        assert conn.execute("SELECT error_code FROM owned_temps").fetchone()[0] == "TEMP_IDENTITY_CHANGED"
        conn.execute("UPDATE runs SET epoch=epoch+1")
    new_lease = lease.model_copy(update={"epoch": lease.epoch+1})
    newer = archive.create_temp(new_lease, item)
    with pytest.raises(ScoutError, match="lease"):
        archive.cleanup_temp(lease, newer)
    assert paths.inside_media(newer).exists()
    archive.cleanup_temp(new_lease, newer)
    assert not paths.inside_media(newer).exists()


def test_active_journal_retains_temp_until_commit(tmp_path):
    from fashion_scout.processes import identity
    runs, paths = setup(tmp_path)
    accept(runs)
    who = identity()
    runs.register_worker("one", who["pid"], who["born"], who["executable"])
    lease = runs.claim("one")
    archive = Archive(paths, runs)
    item = runs.ensure_item(lease, "stage-test")
    runs.start_item(lease, item)
    relative = archive.create_temp(lease, item)
    path = paths.inside_media(relative)
    path.write_bytes(png())
    sha = hashlib.sha256(png()).hexdigest()
    journal = archive.stage(lease, item, relative, "originals/"+sha+".png", sha, len(png()))
    archive.cleanup_temp(lease, relative)
    assert path.exists()
    archive.commit(lease, journal)
    assert not path.exists()
