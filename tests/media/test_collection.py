import json
import pytest
from fashion_scout.domain.models import Discovery, Network
from fashion_scout.services.catalog import product_detail
from tests.t2_helpers import setup, accept, execute, Scenario, product, png


def test_gallery_six_with_one_invalid_is_partial_then_same_run_repairs(tmp_path):
    runs, paths = setup(tmp_path)
    scenario = Scenario([product(images=6)])
    scenario.image_data["/1-5.png"] = b"200 does not mean image"
    run = accept(runs)
    first = execute(runs, paths, run.id, scenario)
    assert first.state == "partial"
    detail = product_detail(runs.db, "futario-1")
    assert detail["first_eligible_at"]
    version = json.loads(detail["versions"][-1]["manifest_json"])
    assert version["expected_count"] == 6 and len(version["missing_ids"]) == 1
    assert len(detail["assets"]) == 1  # Same synthetic bytes deduplicated.
    with runs.db.write() as conn:
        conn.execute("UPDATE product_user_state SET favorite=1,category_override='custom',viewed_at='viewed' WHERE product_id='futario-1'")
    images_before = sum("cdn.shopify.com" in url for url in scenario.calls)
    scenario.image_data["/1-5.png"] = png("blue")
    runs.retry(run.id, "repair")
    second = execute(runs, paths, run.id, scenario)
    assert second.state == "succeeded" and second.id == first.id
    assert sum("cdn.shopify.com" in u for u in scenario.calls) == images_before+1
    detail = product_detail(runs.db, "futario-1")
    assert detail["favorite"] == 1 and detail["viewed_at"] == "viewed"
    assert detail["effective_category"] == "custom"
    assert len(detail["assets"]) == 2
    assert detail["latest_complete_version_id"]
    assert len(detail["versions"]) == 2
    with runs.db.read() as conn:
        assert conn.execute("SELECT seen_before_run FROM collection_products").fetchone()[0] == 0


def test_same_url_content_change_retains_history_order_only_same_content_identity(tmp_path):
    runs, paths = setup(tmp_path)
    item = product(images=2)
    scenario = Scenario([item])
    scenario.image_data["/1-1.png"] = png("blue")
    run = accept(runs)
    assert execute(runs, paths, run.id, scenario).state == "succeeded"
    first = product_detail(runs.db, "futario-1")
    item["images"].reverse()
    second = accept(runs, "second")
    assert execute(runs, paths, second.id, scenario).state == "succeeded"
    reordered = product_detail(runs.db, "futario-1")
    assert first["latest_available_version_id"] == reordered["latest_available_version_id"]
    assert first["latest_available_revision"] != reordered["latest_available_revision"]
    scenario.image_data["/1-1.png"] = png("green")
    third = accept(runs, "third")
    assert execute(runs, paths, third.id, scenario).state == "succeeded"
    changed = product_detail(runs.db, "futario-1")
    assert changed["latest_available_version_id"] != first["latest_available_version_id"]
    assert len(changed["assets"]) == 3


def test_all_images_bad_still_eligible_failed_and_empty_complete_is_success(tmp_path):
    runs, paths = setup(tmp_path)
    scenario = Scenario([product()])
    scenario.image_data["/1-0.png"] = b"bad"
    run = accept(runs)
    assert execute(runs, paths, run.id, scenario).state == "failed"
    detail = product_detail(runs.db, "futario-1")
    assert detail["first_eligible_at"] and detail["latest_available_version_id"] is None
    empty = accept(runs, "empty")
    assert execute(runs, paths, empty.id, Scenario([])).state == "succeeded"


def test_first_baseline_old_metadata_then_subsequent_new_old_date_is_eligible(tmp_path):
    runs, paths = setup(tmp_path)
    first = accept(runs)
    assert execute(runs, paths, first.id, Scenario([product(date="2020-01-01T00:00:00Z")])).state == "succeeded"
    assert product_detail(runs.db, "futario-1")["first_eligible_at"] is None
    next_run = accept(runs, "next")
    scenario = Scenario([product(date="2020-01-01T00:00:00Z"), product("2", date="2020-01-01T00:00:00Z")])
    assert execute(runs, paths, next_run.id, scenario).state == "succeeded"
    assert product_detail(runs.db, "futario-1")["first_eligible_at"] is None
    assert product_detail(runs.db, "futario-2")["first_eligible_at"]
    with runs.db.read() as conn:
        assert [tuple(r) for r in conn.execute("SELECT product_id,seen_before_run,eligible FROM collection_products WHERE run_id=? ORDER BY product_id", (next_run.id,))] == [("futario-1", 1, 0), ("futario-2", 0, 1)]


def test_partial_baseline_not_promoted_and_detail_budget_is_durable(tmp_path):
    runs, paths = setup(tmp_path, discovery=Discovery(page_size=2, max_pages_per_pass=1), max_details=1)
    scenario = Scenario([product(), product("2")])
    run = accept(runs)
    assert execute(runs, paths, run.id, scenario).state == "partial"
    with runs.db.read() as conn:
        assert conn.execute("SELECT baseline_complete FROM sites").fetchone()[0] == 0
    runs.retry(run.id, "retry")
    assert execute(runs, paths, run.id, scenario).state == "partial"
    assert len({u for u in scenario.calls if u.endswith(".js")}) == 1


def test_gallery_unknown_video_does_not_make_full_gallery_partial(tmp_path):
    runs, paths = setup(tmp_path)
    item = product()
    item["media"] = [{"media_type": "video", "sources": []}]
    run = accept(runs)
    assert execute(runs, paths, run.id, Scenario([item])).state == "succeeded"


def test_request_budget_stops_and_preserves_visible_product(tmp_path):
    runs, paths = setup(tmp_path, network=Network(min_interval_ms=1, max_http_requests=3))
    scenario = Scenario([product(images=2)])
    run = accept(runs)
    assert execute(runs, paths, run.id, scenario).state == "failed"
    assert len(scenario.calls) == 3  # Two discovery + one detail, no image request.
    assert product_detail(runs.db, "futario-1")["first_eligible_at"]


def test_partial_latest_observation_preserves_previous_usable_and_complete(tmp_path):
    runs, paths = setup(tmp_path)
    scenario = Scenario([product()])
    first = accept(runs)
    assert execute(runs, paths, first.id, scenario).state == "succeeded"
    old = product_detail(runs.db, "futario-1")
    scenario.image_data["/1-0.png"] = b"not an image"
    second = accept(runs, "second")
    assert execute(runs, paths, second.id, scenario).state == "failed"
    current = product_detail(runs.db, "futario-1")
    assert current["latest_available_version_id"] == old["latest_available_version_id"]
    assert current["latest_complete_version_id"] == old["latest_complete_version_id"]
    assert current["latest_observed_version_id"] != old["latest_observed_version_id"]
    assert current["current_gallery"]["missing_ids"] and current["media_state"] == "failed"


def test_byte_budget_reservation_prevents_new_request(tmp_path):
    from fashion_scout.domain.models import Storage
    runs, paths = setup(tmp_path, storage=Storage(run_download_bytes=1024, min_free_bytes=1))
    scenario = Scenario([product()])
    run = accept(runs)
    assert execute(runs, paths, run.id, scenario).state == "failed"
    assert scenario.calls == []
    with runs.db.read() as conn:
        assert conn.execute("SELECT request_count,downloaded_bytes FROM collection_runs").fetchone()[:] == (0,0)
