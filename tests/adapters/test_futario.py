import pytest
from fashion_scout.adapters.futario import parse_date, normalize
from fashion_scout.domain import ScoutError
from tests.t2_helpers import setup, accept, execute, Scenario, product


@pytest.mark.parametrize("raw,reason", [(None,"missing"),("wrong","invalid"),
    ("2026-10-06T10:00:00","no_timezone"),("2026-10-07T00:00:00Z","future")])
def test_unknown_dates(raw, reason):
    assert parse_date(raw, "2026-10-06T12:00:00Z") == (None, reason)


def test_timezone_boundary_and_variant_gallery_relation():
    item = product(date="2026-10-06T20:00:00+08:00")
    parsed = normalize(item, "2026-10-06T12:00:00Z", True)
    assert parsed.source_published_at == "2026-10-06T12:00:00Z"
    assert parsed.images[0].variant_ids == ["10"]


def test_bad_schema_does_not_fall_back_to_browser():
    with pytest.raises(ScoutError):
        normalize({"id":1,"title":"x","handle":"../escape"}, "2026-10-06T12:00:00Z", True)


def test_repeated_page_marks_partial_without_infinite_scan(tmp_path):
    runs, paths = setup(tmp_path)
    scenario = Scenario([product(),product("2")])
    scenario.pages = lambda page: scenario.products
    run = accept(runs)
    assert execute(runs, paths, run.id, scenario).state == "partial"
    assert sum("/products.json" in u for u in scenario.calls) == 2


def test_second_pass_reorder_is_stable_set(tmp_path):
    runs, paths = setup(tmp_path)
    scenario = Scenario([product(),product("2"),product("3")])
    pages = iter([scenario.products[:2],scenario.products[2:],scenario.products[1:],scenario.products[:1]])
    scenario.pages = lambda page: next(pages)
    run = accept(runs)
    assert execute(runs, paths, run.id, scenario).state == "succeeded"


def test_second_pass_set_change_is_partial(tmp_path):
    runs, paths = setup(tmp_path)
    scenario = Scenario([product(),product("2")])
    pages = iter([[scenario.products[0]], [scenario.products[1]]])
    scenario.pages = lambda page: next(pages)
    run = accept(runs)
    assert execute(runs, paths, run.id, scenario).state == "partial"
