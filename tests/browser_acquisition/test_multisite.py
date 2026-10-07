"""Synthetic normal-page facts exercise the production API, Worker and Archive."""
import json
import pytest
from pydantic import ValidationError
from fashion_scout import client as fixed_client
from fashion_scout.domain.browser_source import BrowserProduct, Detail, Listing
from fashion_scout.domain.models import BrowserLimits, CreateRun, LEGACY_BROWSER_DEFAULTS, run_request_payload
from fashion_scout.domain.sites import BROWSER_SITES
from fashion_scout.services.runs import canonical, digest
from .conftest import eventually, worker
from .test_bridge import key, ok, observe, tickets, upload, finish, status, image_bytes


def product(site_id, *, listing_link=False):
    site = BROWSER_SITES[site_id]
    prefix = site.entry if listing_link else "https://" + site.product_host
    return {"source_id": "12345", "handle": "synthetic-dress", "title": "Synthetic browser dress",
            "url": prefix + "/products/synthetic-dress"}


def listing_fact(site_id, *, number=1, page=1, terminal=False, products=None):
    site = BROWSER_SITES[site_id]
    page_url = site.entry + ("?page=" + str(page) if page > 1 and site_id != "futario" else "")
    return {"kind": "listing", "page_url": page_url, "pass_number": number, "page_number": page,
            "terminal": terminal, "products": [product(site_id, listing_link=site_id == "rihoas")] if products is None else products}


def detail_fact(site_id):
    site = BROWSER_SITES[site_id]
    return {"kind": "detail", "product": product(site_id), "images": [{"source_image_id": "0",
            "url": "https://" + site.product_host + "/cdn/shop/files/synthetic-0.jpg?v=123&width=740", "ordinal": 0}],
            "gallery_end_observed": True, "expected_count": 1, "observed_options": ["Black", "S", "M"]}


def start_site(client, site_id, **overrides):
    accepted = ok(client.post("/v1/runs", json={"request_key": key(), "trigger": "skill", "overrides": {
        "source_mode": "browser", "site_ids": [site_id], "browser": {"idle_seconds": 10}, **overrides}}))
    rid = accepted["run"]["id"]
    prefix = "/v1/runs/" + rid + "/browser-source"
    attached = ok(client.post(prefix + "/attach", json={"request_key": key()}))
    assert attached["site_id"] == site_id and attached["adapter_version"] == BROWSER_SITES[site_id].adapter_version
    return rid, prefix, attached["session_id"]


def test_three_sequential_sites_archive_separate_products_and_preserve_user_state(env):
    client, runs, paths, app = env
    previous_ticket = None
    expected_ids = []
    with worker(paths):
        for n, site_id in enumerate(BROWSER_SITES):
            rid, prefix, sid = start_site(client, site_id)
            snapshot = runs.get(rid).snapshot
            assert snapshot.site_ids == [site_id] and snapshot.site_entries == {site_id: BROWSER_SITES[site_id].entry}
            assert snapshot.adapter_versions == {site_id: BROWSER_SITES[site_id].adapter_version}
            bad_attach = client.post(prefix + "/attach", json={"request_key": key(), "adapter_version":
                BROWSER_SITES["rihoas" if site_id == "futario" else "futario"].adapter_version})
            assert bad_attach.status_code == 422 and bad_attach.json()["error"]["code"] == "SOURCE_ADAPTER_MISMATCH"
            for number in (1, 2):
                observe(client, prefix, sid, listing_fact(site_id, number=number))
                observe(client, prefix, sid, listing_fact(site_id, number=number, page=2, terminal=True, products=[]))
            observe(client, prefix, sid, detail_fact(site_id))
            ticket = tickets(client, prefix, 1)[0]
            pid = site_id + "-12345"
            assert ticket["product_id"] == pid and ticket["source_url"] == detail_fact(site_id)["images"][0]["url"]
            assert pid not in [p["id"] for p in ok(client.get("/v1/products"))["items"]]
            audited = ok(client.get("/v1/products/" + pid))["product"]
            assert not audited["images"] and audited["source"]["source_published_at"] is None
            if previous_ticket:
                assert upload(client, prefix, sid, previous_ticket).status_code == 404
                assert client.post(prefix + "/assets/" + previous_ticket["id"] + "/failure", json={
                    "request_key": key(), "session_id": sid, "code": "HOST_ASSET_UNAVAILABLE"}).status_code == 404
            wrong_url = {**ticket, "source_url": detail_fact("rihoas" if site_id == "futario" else "futario")["images"][0]["url"]}
            assert upload(client, prefix, sid, wrong_url).status_code == 422
            ok(upload(client, prefix, sid, ticket, data=image_bytes(n)))
            eventually(lambda: status(client, prefix)["tickets"][0]["state"] == "archived")
            eventually(lambda: pid in [p["id"] for p in ok(client.get("/v1/products"))["items"]])
            expected_ids.append(pid)
            finish(client, prefix, sid)
            eventually(lambda: runs.get(rid).state == "partial")
            displayed = ok(client.get("/v1/products/" + pid))["product"]
            assert displayed["site_id"] == site_id and displayed["site_name"] == BROWSER_SITES[site_id].name
            assert displayed["album"]["stored_count"] == 1 and displayed["album"]["coverage_scope"] == ["browser.gallery"]
            assert displayed["latest_complete_version_id"] is None
            with runs.db.read() as conn:
                assert [r[0] for r in conn.execute("SELECT site_id FROM site_runs WHERE run_id=?", (rid,))] == [site_id]
                assert conn.execute("SELECT site_id FROM products WHERE id=?", (pid,)).fetchone()[0] == site_id
                assert conn.execute("SELECT adapter_version FROM browser_sessions WHERE id=?", (sid,)).fetchone()[0] == BROWSER_SITES[site_id].adapter_version
                visited = {pid.rsplit("-", 1)[0] for pid in expected_ids}
                assert {r["id"] for r in conn.execute("SELECT id FROM sites WHERE baseline_complete=1")} == visited
            previous_ticket = ticket
        assert {p["id"] for p in ok(client.get("/v1/products"))["items"]} == set(expected_ids)
        first = ok(client.get("/v1/products/futario-12345"))["product"]
        ok(client.patch("/v1/products/futario-12345/user-state", json={"expected_revision": first["user_state"]["revision"],
            "favorite": True, "excluded": True, "category_override": "tops"}))["user_state"]
        ok(client.post("/v1/products/futario-12345/view-events", json={"event_id": key(),
            "version_id": first["version_id"], "version_revision": first["version_revision"]}))
        retained = ok(client.get("/v1/products/futario-12345"))["product"]["user_state"]
        # A normal recheck of the same numeric product never resets human choices.
        rid, prefix, sid = start_site(client, "futario")
        observe(client, prefix, sid, listing_fact("futario")); observe(client, prefix, sid, detail_fact("futario"))
        ok(upload(client, prefix, sid, tickets(client, prefix, 1)[0], data=image_bytes(9)))
        finish(client, prefix, sid); eventually(lambda: runs.get(rid).state == "partial")
        assert ok(client.get("/v1/products/futario-12345"))["product"]["user_state"] == retained
        assert "futario-12345" not in [p["id"] for p in ok(client.get("/v1/products"))["items"]]
        assert [p["id"] for p in ok(client.get("/v1/products?view=favorites"))["items"]] == ["futario-12345"]
        with runs.db.read() as conn:
            assert conn.execute("SELECT COUNT(*) FROM products").fetchone()[0] == 3
            assert conn.execute("SELECT COUNT(*) FROM collection_http").fetchone()[0] == 0
            assert conn.execute("SELECT COUNT(*) FROM archive_journal WHERE state='committed'").fetchone()[0] == 4


@pytest.mark.parametrize("site_id", list(BROWSER_SITES))
def test_frozen_run_rejects_other_site_and_active_scope(env, site_id):
    client, runs, paths, app = env
    rid, prefix, sid = start_site(client, site_id)
    other = "rihoas" if site_id == "futario" else "futario"
    before = status(client, prefix)
    for fact in (listing_fact(other), detail_fact(other)):
        result = client.post(prefix + "/observations", json={"request_key": key(), "session_id": sid, "observation": fact})
        assert result.status_code == 422 and result.json()["error"]["code"] == "SOURCE_SITE_MISMATCH"
    assert status(client, prefix)["messages"] == before["messages"] == []
    with runs.db.read() as conn:
        assert conn.execute("SELECT observations FROM browser_runs WHERE run_id=?", (rid,)).fetchone()[0] == 0
    result = client.post("/v1/runs", json={"request_key": key(), "trigger": "skill", "overrides": {
        "source_mode": "browser", "site_ids": [other]}})
    assert result.status_code == 409 and result.json()["error"]["code"] == "SITE_SCOPE_CONFLICT"
    assert runs.get(rid).snapshot.site_ids == [site_id]


@pytest.mark.parametrize("site_id", list(BROWSER_SITES))
def test_real_pagination_url_must_match_page_and_registry(site_id):
    base = listing_fact(site_id, page=2)
    assert Listing.model_validate(base).page_number == 2
    entry = BROWSER_SITES[site_id].entry
    for url in (entry + "?page=0", entry + "?page=02", entry + "?page=1001", entry + "?page=3",
                entry + "?page=2&sort_by=created-descending", entry + "?page=2&page=2",
                entry + "?page=%32", entry + "/other?page=2", entry + "?page=2#fragment",
                entry.replace("https://", "http://") + "?page=2", entry.replace("https://", "https://user@") + "?page=2"):
        with pytest.raises(ValidationError): Listing.model_validate({**base, "page_url": url})
    if site_id != "futario":
        with pytest.raises(ValidationError): Listing.model_validate({**base, "page_url": entry})


@pytest.mark.parametrize("site_id", list(BROWSER_SITES))
def test_product_gallery_hosts_and_unrelated_cdn_paths_are_closed(site_id):
    fact = detail_fact(site_id)
    assert Detail.model_validate(fact).product.source_id == "12345"
    other = "rihoas" if site_id == "futario" else "futario"
    for url in (detail_fact(other)["images"][0]["url"], "https://lantern.roeye.com/image.jpg",
                "https://marketing.cloudfront.net/image.jpg", "https://cdn.shopify.com/s/files/1/9999/9999/9999/x.jpg",
                "https://" + BROWSER_SITES[site_id].product_host + "/unrelated/x.jpg"):
        with pytest.raises(ValidationError): Detail.model_validate({**fact, "images": [{**fact["images"][0], "url": url}]})
    with pytest.raises(ValidationError): Listing.model_validate({**listing_fact(site_id), "products": [product(other)]})
    with pytest.raises(ValidationError): BrowserProduct.model_validate({**product(site_id), "handle": "different"})


def test_old_futario_frozen_defaults_request_key_and_saved_plan_survive(env):
    client, runs, paths, app = env
    # Compatibility-only fixture: reconstruct the old persisted fingerprint and
    # complete old limits. Positive acquisition tests above do not seed source SQL.
    body = {"request_key": key(), "trigger": "skill", "overrides": {"source_mode": "browser", "browser": {"idle_seconds": 9}}}
    request = CreateRun.model_validate(body)
    accepted = ok(client.post("/v1/runs", json=body))
    rid = accepted["run"]["id"]
    with runs.db.write() as conn:
        snapshot = json.loads(conn.execute("SELECT snapshot_json FROM runs WHERE id=?", (rid,)).fetchone()[0])
        snapshot["browser"] = {**LEGACY_BROWSER_DEFAULTS, "idle_seconds": 9}
        conn.execute("UPDATE runs SET snapshot_json=? WHERE id=?", (canonical(snapshot), rid))
        conn.execute("UPDATE run_requests SET payload_hash=? WHERE request_key=?", (digest(run_request_payload(request, legacy_browser=True)), body["request_key"]))
        plan = json.loads(conn.execute("SELECT plan_json FROM settings").fetchone()[0]); plan["browser"] = LEGACY_BROWSER_DEFAULTS
        conn.execute("UPDATE settings SET plan_json=?", (canonical(plan),))
        saved = conn.execute("SELECT plan_json,revision FROM settings").fetchone()
        saved_plan, saved_revision = tuple(saved)
    runs.initialize()
    assert ok(client.post("/v1/runs", json=body))["run"]["id"] == rid
    changed = {**body, "overrides": {**body["overrides"], "browser": {"idle_seconds": 8}}}
    assert client.post("/v1/runs", json=changed).status_code == 409
    assert runs.get(rid).snapshot.browser.max_selected_assets == 12
    assert runs.get(rid).snapshot.browser.max_observations == 40
    assert ok(client.get("/v1/settings/default-plan"))["plan"]["browser"] == BrowserLimits().model_dump()
    prefix = "/v1/runs/" + rid + "/browser-source"
    attached = ok(client.post(prefix + "/attach", json={"request_key": key()}))
    assert attached["limits"]["max_selected_assets"] == 12
    ok(client.post("/v1/runs/" + rid + "/cancel", json={"request_key": key()}))
    new, _, _ = start_site(client, "rihoas")
    assert runs.get(new).snapshot.browser.max_selected_assets == 240
    with runs.db.read() as conn:
        assert tuple(conn.execute("SELECT plan_json,revision FROM settings").fetchone()) == (saved_plan, saved_revision)


@pytest.mark.parametrize("overrides", [{"source_mode": "http"},
    {"source_mode": "http", "browser": {"idle_seconds": 9}},
    {"source_mode": "browser", "browser": {}}])
def test_legacy_v2_explicit_mode_keys_keep_original_receipts(env, overrides):
    client, runs, paths, app = env
    body = {"request_key": key(), "trigger": "skill", "overrides": overrides}
    request = CreateRun.model_validate(body)
    rid = ok(client.post("/v1/runs", json=body))["run"]["id"]
    with runs.db.write() as conn:
        conn.execute("UPDATE run_requests SET payload_hash=? WHERE request_key=?",
            (digest(run_request_payload(request, legacy_browser=True)), body["request_key"]))
        original = tuple(conn.execute("SELECT payload_hash,response_json FROM run_requests WHERE request_key=?", (body["request_key"],)).fetchone())
    assert ok(client.post("/v1/runs", json=body))["run"]["id"] == rid
    ok(client.post("/v1/runs/" + rid + "/cancel", json={"request_key": key()}))
    assert ok(client.post("/v1/runs", json=body))["run"]["state"] == "cancelled"
    with runs.db.read() as conn:
        assert tuple(conn.execute("SELECT payload_hash,response_json FROM run_requests WHERE request_key=?", (body["request_key"],)).fetchone()) == original


def test_same_title_simpleretro_cards_keep_distinct_numeric_identity(env):
    client, runs, paths, app = env
    with worker(paths):
        rid, prefix, sid = start_site(client, "simpleretro")
        one = product("simpleretro")
        two = {**one, "source_id": "12346", "handle": "synthetic-dress-beige",
               "url": "https://www.simpleretro.com/products/synthetic-dress-beige?variant=123"}
        observe(client, prefix, sid, listing_fact("simpleretro", products=[one, two]))
        for n, value in enumerate((one, two)):
            fact = detail_fact("simpleretro")
            observe(client, prefix, sid, {**fact, "product": value, "images": [{**fact["images"][0],
                "url": fact["images"][0]["url"].replace("synthetic-0", "synthetic-" + str(n))}]})
        choices = tickets(client, prefix, 2)
        assert {t["product_id"] for t in choices} == {"simpleretro-12345", "simpleretro-12346"}
        for n, ticket in enumerate(choices): ok(upload(client, prefix, sid, ticket, data=image_bytes(n)))
        finish(client, prefix, sid); eventually(lambda: runs.get(rid).state == "partial")
        items = ok(client.get("/v1/products"))["items"]
        assert len(items) == 2 and items[0]["title"] == items[1]["title"]


def test_custom_byte_limits_survive_temporary_browser_overrides(env):
    client, runs, paths, app = env
    before = ok(client.get("/v1/settings/default-plan"))
    custom = {**before["plan"]["browser"], "max_selected_assets": 3, "max_received_bytes": 1024}
    ok(client.patch("/v1/settings/default-plan", json={"expected_revision": before["revision"], "browser": custom}))
    rid, _, _ = start_site(client, "simpleretro")
    assert runs.get(rid).snapshot.browser.max_received_bytes == 1024
    assert runs.get(rid).snapshot.browser.max_selected_assets == 3
    assert runs.get(rid).snapshot.browser.idle_seconds == 10


def test_sites_capabilities_and_fixed_client_payloads(env):
    client, runs, paths, app = env
    sites = ok(client.get("/v1/sites"))
    assert {s["id"] for s in sites["items"]} == set(BROWSER_SITES)
    intent_key = key()
    for site_id, site in BROWSER_SITES.items():
        raw = {"new_intent": True, "overrides": {"source_mode": "browser", "site_ids": [site_id]}}
        parsed = fixed_client.validate("start", raw)
        assert fixed_client.write_spec("start", parsed, intent_key)["body"]["overrides"]["site_ids"] == [site_id]
        attach = {"new_intent": True, "run_id": "run", "adapter_version": site.adapter_version}
        spec = fixed_client.write_spec("browser-attach", fixed_client.validate("browser-attach", attach), intent_key)
        assert spec["body"]["adapter_version"] == site.adapter_version
    for site_ids, mode in ((["futario", "rihoas"], "browser"), (["simpleretro"], "http")):
        value = client.patch("/v1/settings/default-plan", json={"expected_revision": 1, "source_mode": mode, "site_ids": site_ids})
        assert value.status_code == 422
