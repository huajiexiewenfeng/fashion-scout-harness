import json
import pytest
from fashion_scout.db.archive import Archive
from fashion_scout.services.catalog import Catalog, product_detail
from tests.t2_helpers import setup, accept, execute, Scenario, product


def test_crash_after_stage_missing_temp_refetches_via_real_collector(tmp_path,monkeypatch):
    runs,paths=setup(tmp_path)
    scenario=Scenario([product()])
    run=accept(runs)
    commit=Archive.commit
    def crash(self,lease,journal): raise RuntimeError("test process boundary after stage")
    monkeypatch.setattr(Archive,"commit",crash)
    with pytest.raises(RuntimeError):
        execute(runs,paths,run.id,scenario)
    with runs.db.read() as conn:
        row=conn.execute("SELECT * FROM archive_journal").fetchone()
        paths.inside_media(row["temp_path"]).unlink()
    monkeypatch.setattr(Archive,"commit",commit)
    runs.retry(run.id,"repair")
    assert execute(runs,paths,run.id,scenario).state=="succeeded"
    assert sum("cdn.shopify.com" in u for u in scenario.calls)==2
    with runs.db.read() as conn:
        assert conn.execute("SELECT COUNT(*) FROM assets").fetchone()[0]==1
        assert conn.execute("SELECT seen_before_run FROM collection_products").fetchone()[0]==0
        assert conn.execute("SELECT COUNT(*) FROM archive_journal_events WHERE kind='retryable'").fetchone()[0]==1
    assert product_detail(runs.db,"futario-1")["latest_available_version_id"]


def test_crash_after_archive_commit_reuses_completed_bytes(tmp_path,monkeypatch):
    runs,paths=setup(tmp_path)
    scenario=Scenario([product()])
    run=accept(runs)
    save=Catalog.image_result
    def crash(*args,**kwargs): raise RuntimeError("after archive, before catalog link")
    monkeypatch.setattr(Catalog,"image_result",crash)
    with pytest.raises(RuntimeError):
        execute(runs,paths,run.id,scenario)
    monkeypatch.setattr(Catalog,"image_result",save)
    runs.retry(run.id,"repair")
    assert execute(runs,paths,run.id,scenario).state=="succeeded"
    assert sum("cdn.shopify.com" in u for u in scenario.calls)==1
