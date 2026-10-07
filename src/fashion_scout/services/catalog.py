"""Fenced collection persistence and stable downstream read interfaces."""
import json
import time
from fashion_scout.domain import ScoutError
from fashion_scout.domain.models import SourceProduct
from fashion_scout.adapters.futario import category
from fashion_scout.services.runs import canonical, digest, new_id, timestamp


class Catalog:
    def __init__(self, runs, lease, paths, execution_started=None):
        self.runs, self.lease, self.paths = runs, lease, paths
        self.run = runs.get(lease.run_id)
        self.snapshot = self.run.snapshot
        self.execution_started = time.monotonic() if execution_started is None else execution_started
        with runs.db.write() as conn:
            runs.fence(conn, lease)
            conn.execute("INSERT OR IGNORE INTO collection_runs(run_id,started_at) VALUES (?,?)", (lease.run_id, time.time()))

    def request_charge(self, url, kind):
        with self.runs.db.write() as conn:
            self.runs.fence(conn, self.lease)
            throttle = conn.execute("SELECT not_before FROM network_throttle WHERE site_id='futario'").fetchone()
            if throttle and throttle[0] is None:
                raise ScoutError("RATE_LIMIT_REVIEW_REQUIRED", "Prior server wait is unknown; preserve the rate-limit hold")
            if throttle and time.time() < throttle[0]:
                raise ScoutError("RETRY_DEFERRED", "Source backoff is still active")
            row = conn.execute("SELECT * FROM collection_runs WHERE run_id=?", (self.lease.run_id,)).fetchone()
            self.check_time_budget()
            if row["downloaded_bytes"] >= self.snapshot.storage.run_download_bytes:
                raise ScoutError("DOWNLOAD_BUDGET", "Run download budget reached")
            # Serial transfers reserve the maximum body plus one bounded socket chunk.
            # This may stop early; it prevents a chunk crossing the total run cap.
            transfer_limit = self.snapshot.storage.max_image_bytes if kind == "image" else 8 * 1024**2
            if self.snapshot.storage.run_download_bytes-row["downloaded_bytes"] < transfer_limit+65536:
                raise ScoutError("DOWNLOAD_BUDGET", "Insufficient remaining transfer reservation")
            if row["request_count"] >= self.snapshot.network.max_http_requests:
                raise ScoutError("REQUEST_BUDGET", "Run HTTP budget reached")
            if kind == "image" and row["image_requests"] >= self.snapshot.network.max_image_requests:
                raise ScoutError("IMAGE_REQUEST_BUDGET", "Image request budget reached")
            if kind == "discovery" and row["discovery_requests"] >= self.snapshot.discovery.max_requests:
                raise ScoutError("DISCOVERY_BUDGET", "Discovery HTTP budget reached")
            if kind == "detail":
                known = conn.execute("SELECT DISTINCT url FROM collection_http WHERE run_id=? AND kind='detail'", (self.lease.run_id,)).fetchall()
                if url not in {r[0] for r in known} and len(known) >= self.snapshot.max_details:
                    raise ScoutError("DETAIL_BUDGET", "Run distinct detail budget reached")
            conn.execute("UPDATE collection_runs SET request_count=request_count+1,image_requests=image_requests+?,discovery_requests=discovery_requests+? WHERE run_id=?", (int(kind=="image"), int(kind=="discovery"), self.lease.run_id))
            return conn.execute("INSERT INTO collection_http(run_id,attempt,kind,url,at) VALUES (?,?,?,?,?)", (self.lease.run_id, self.run.attempt, kind, url, timestamp(time.time()))).lastrowid

    def response_record(self, request_id, status, retry_after, peer):
        from fashion_scout.media.http import retry_seconds
        delay = None
        mode = "server"
        received_at = time.time()
        if status == 429 or (status >= 500 and retry_after):
            try:
                if not retry_after:
                    mode = "local_policy"
                delay = retry_seconds(retry_after) if retry_after else 2
            except ScoutError:
                mode, delay = "local_policy", 2
        with self.runs.db.write() as conn:
            self.runs.fence(conn, self.lease)
            conn.execute("INSERT INTO collection_http_results(request_seq,status,retry_after,peer,received_at) VALUES (?,?,?,?,?)", (request_id, status, retry_after, peer, received_at))
            if delay is not None:
                conn.execute("INSERT INTO network_throttle VALUES ('futario',?,?,?,?) ON CONFLICT(site_id) DO UPDATE SET not_before=MAX(not_before,excluded.not_before),mode=excluded.mode,request_seq=excluded.request_seq,recorded_at=excluded.recorded_at", (received_at+delay, mode, request_id, received_at))

    def bytes_charge(self, size):
        with self.runs.db.write() as conn:
            self.runs.fence(conn, self.lease)
            row = conn.execute("SELECT downloaded_bytes,started_at FROM collection_runs WHERE run_id=?", (self.lease.run_id,)).fetchone()
            conn.execute("UPDATE collection_runs SET downloaded_bytes=downloaded_bytes+? WHERE run_id=?", (size, self.lease.run_id))
        # Charge actual received bytes even when crossing the limit; never reset on retry.
        if row["downloaded_bytes"] + size > self.snapshot.storage.run_download_bytes:
            raise ScoutError("DOWNLOAD_BUDGET", "Run download budget reached")
        self.check_time_budget()

    def check_time_budget(self):
        if time.monotonic() - self.execution_started >= self.snapshot.network.run_total_seconds:
            raise ScoutError("RUN_TIME_BUDGET", "Execution time allowance reached; explicit same-Run retry can resume within remaining cumulative limits")

    def issue(self, code, evidence, retryable=True):
        # These frozen cumulative caps cannot be repaired by retrying this Run.
        if code in {"REQUEST_BUDGET", "IMAGE_REQUEST_BUDGET", "DISCOVERY_BUDGET", "DETAIL_BUDGET", "DOWNLOAD_BUDGET"}:
            retryable = False
            evidence += ";action=review_frozen_limits_then_explicit_new_run;same_run_limits_do_not_reset"
        with self.runs.db.write() as conn:
            self.runs.fence(conn, self.lease)
            identifier = digest([self.lease.run_id, self.run.attempt, code, evidence])
            conn.execute("INSERT OR IGNORE INTO issues VALUES (?,?,?,?,?)",
                         (identifier, self.lease.run_id, code, int(retryable), evidence))

    def discover_product(self, product):
        pid = "futario-" + product.source_id
        now = timestamp(time.time())
        with self.runs.db.write() as conn:
            self.runs.fence(conn, self.lease)
            existing = conn.execute("SELECT * FROM products WHERE id=?", (pid,)).fetchone()
            seen = bool(conn.execute("SELECT 1 FROM run_seen_products WHERE run_id=? AND product_id=?", (self.lease.run_id, pid)).fetchone())
            known_archive = existing is not None and existing["latest_available_version_id"] is not None
            if known_archive:
                eligible, rule = True, "recheck_archived"
            elif self.snapshot.discovery_baseline_complete["futario"] and not seen:
                eligible, rule = True, "first_discovered_after_baseline"
            elif product.source_published_at is None:
                eligible, rule = self.snapshot.unknown_date_policy == "include", "unknown_" + self.snapshot.unknown_date_policy
            else:
                from datetime import datetime
                date = datetime.fromisoformat(product.source_published_at.replace("Z", "+00:00"))
                start = datetime.fromisoformat(self.snapshot.window_start.replace("Z", "+00:00"))
                end = datetime.fromisoformat(self.snapshot.window_end.replace("Z", "+00:00"))
                eligible, rule = start <= date <= end, "source_date_window"
            conn.execute("INSERT OR IGNORE INTO products(id,site_id,source_id,first_seen_at) VALUES (?,'futario',?,?)", (pid, product.source_id, now))
            conn.execute("INSERT OR IGNORE INTO product_user_state(product_id) VALUES (?)", (pid,))
            conn.execute("INSERT OR IGNORE INTO collection_products(run_id,product_id,seen_before_run,eligible,rule,listing_json) VALUES (?,?,?,?,?,?)", (self.lease.run_id, pid, int(seen), int(eligible), rule, product.model_dump_json()))
            frozen = conn.execute("SELECT eligible,rule FROM collection_products WHERE run_id=? AND product_id=?", (self.lease.run_id, pid)).fetchone()
            conn.execute("UPDATE products SET category_raw=?,category_key=?,first_eligible_at=CASE WHEN ? THEN COALESCE(first_eligible_at,?) ELSE first_eligible_at END,eligibility_rule_ref=CASE WHEN ? THEN COALESCE(eligibility_rule_ref,?) ELSE eligibility_rule_ref END WHERE id=?",
                (product.category_raw, category(product.category_raw), frozen["eligible"], now, frozen["eligible"], self.lease.run_id + ":" + frozen["rule"], pid))
        return pid

    def page(self, pass_number, page_number, page):
        evidence = {k:v for k,v in page.items() if k!="products"}
        with self.runs.db.write() as conn:
            self.runs.fence(conn, self.lease)
            conn.execute("INSERT OR IGNORE INTO collection_page_attempts VALUES (?,?,?,?,?,?)",
                (self.lease.run_id, self.run.attempt, pass_number, page_number, page["signature"], canonical(evidence)))

    def discovery_result(self, result):
        with self.runs.db.write() as conn:
            self.runs.fence(conn, self.lease)
            conn.execute("UPDATE collection_runs SET discovery_complete=?,discovery_json=? WHERE run_id=?", (int(result["complete"]), canonical(result), self.lease.run_id))
            conn.execute("INSERT INTO site_runs VALUES (?,'futario',?) ON CONFLICT(run_id,site_id) DO UPDATE SET coverage_json=excluded.coverage_json", (self.lease.run_id, canonical(result)))
            if result["complete"]:
                conn.execute("UPDATE sites SET baseline_complete=1 WHERE id='futario'")

    def rows(self):
        with self.runs.db.read() as conn:
            return [dict(r) for r in conn.execute("SELECT * FROM collection_products WHERE run_id=? ORDER BY product_id", (self.lease.run_id,))]

    def save_detail(self, pid, product):
        with self.runs.db.write() as conn:
            self.runs.fence(conn, self.lease)
            conn.execute("UPDATE collection_products SET detail_json=?,detail_error=NULL WHERE run_id=? AND product_id=?", (product.model_dump_json(), self.lease.run_id, pid))
            revision = conn.execute("SELECT COALESCE(MAX(revision),0)+1 FROM observations WHERE run_id=? AND product_id=? AND attempt=?", (self.lease.run_id, pid, self.run.attempt)).fetchone()[0]
            oid = new_id()
            dates = {"source_published_at": product.source_published_at, "raw_published_at": product.raw_published_at,
                     "raw_created_at": product.raw_created_at, "reason": product.date_reason}
            conn.execute("INSERT INTO observations VALUES (?,?,?,?,?,?,?,?)",
                (oid, self.lease.run_id, pid, self.run.attempt, revision, timestamp(time.time()), product.model_dump_json(), canonical(dates)))
            conn.execute("UPDATE products SET latest_observation_id=?,category_raw=?,category_key=? WHERE id=?", (oid, product.category_raw, category(product.category_raw), pid))

    def detail_error(self, pid, code):
        with self.runs.db.write() as conn:
            self.runs.fence(conn, self.lease)
            conn.execute("UPDATE collection_products SET detail_error=? WHERE run_id=? AND product_id=?", (code, self.lease.run_id, pid))
        self.issue(code, "product:" + pid)

    def images(self, pid):
        with self.runs.db.read() as conn:
            return [dict(row) for row in conn.execute("SELECT c.*,w.state,w.output_json FROM collection_images c JOIN work_items w ON w.id=c.item_id WHERE c.run_id=? AND c.product_id=? ORDER BY ordinal", (self.lease.run_id, pid))]

    def prepare_images(self, pid, product):
        for image in product.images:
            key = "image:" + pid + ":" + image.source_image_id
            item = self.runs.ensure_item(self.lease, key)
            with self.runs.db.write() as conn:
                self.runs.fence(conn, self.lease)
                conn.execute("INSERT OR IGNORE INTO collection_images VALUES (?,?,?,?,?,?,?,NULL,NULL)",
                    (self.lease.run_id, pid, image.source_image_id, item, image.url, image.ordinal, canonical(image.variant_ids)))

    def image_result(self, pid, source_id, asset=None, code=None):
        with self.runs.db.write() as conn:
            self.runs.fence(conn, self.lease)
            conn.execute("UPDATE collection_images SET asset_id=?,error_code=? WHERE run_id=? AND product_id=? AND source_image_id=?", (asset, code, self.lease.run_id, pid, source_id))

    def freeze_version(self, pid, product, coverage_scope="product.images"):
        rows = self.images(pid)
        with self.runs.db.write() as conn:
            self.runs.fence(conn, self.lease)
            images = []
            for row in rows:
                asset = conn.execute("SELECT * FROM assets WHERE id=?", (row["asset_id"],)).fetchone() if row["asset_id"] else None
                images.append({"source_image_id": row["source_image_id"], "url": row["source_url"],
                    "ordinal": row["ordinal"], "variant_ids": json.loads(row["variant_json"]),
                    "asset_id": asset["id"] if asset else None, "sha256": asset["sha256"] if asset else None,
                    "error_code": row["error_code"]})
            missing = [r["source_image_id"] for r in images if not r["asset_id"]]
            complete = product.enumeration_complete and not missing
            # Material identity uses bytes, independent of image order, URL or source IDs.
            content = digest({"sha256": sorted({r["sha256"] for r in images if r["sha256"]})})
            vid = digest([pid, content])
            manifest = {"product": product.model_dump(mode="json"), "images": images,
                "promised_scopes": [coverage_scope], "expected_count": len(product.images),
                "enumeration_complete": product.enumeration_complete, "missing_ids": missing,
                "complete": complete, "content_digest": content, "capability_notes": product.capability_notes}
            mdigest = digest(manifest)
            existing = conn.execute("SELECT id,revision FROM product_versions WHERE product_id=? AND manifest_digest=?", (pid, mdigest)).fetchone()
            if existing:
                vid, revision = existing
            else:
                revision = conn.execute("SELECT COALESCE(MAX(revision),0)+1 FROM product_versions WHERE id=?", (vid,)).fetchone()[0]
                conn.execute("INSERT INTO product_versions(id,revision,product_id,manifest_digest,manifest_json,content_digest) VALUES (?,?,?,?,?,?)", (vid, revision, pid, mdigest, canonical(manifest), content))
                for row in images:
                    conn.execute("INSERT INTO version_images VALUES (?,?,?,?,?,?)", (vid, revision, row["source_image_id"], row["url"], row["ordinal"], row["asset_id"]))
            usable = any(r["asset_id"] for r in images)
            conn.execute("UPDATE products SET latest_observed_version_id=?,latest_observed_revision=? WHERE id=?", (vid, revision, pid))
            if usable:
                conn.execute("UPDATE products SET latest_available_version_id=?,latest_available_revision=? WHERE id=?", (vid, revision, pid))
            if complete and usable and coverage_scope == "product.images":
                conn.execute("UPDATE products SET latest_complete_version_id=?,latest_complete_revision=? WHERE id=?", (vid, revision, pid))
        return {"usable": usable, "complete": complete and usable, "version_id": vid, "revision": revision}


def product_detail(db, product_id):
    """T3/T5 stable read: retained versions/assets and human category precedence."""
    with db.read() as conn:
        row = conn.execute("SELECT p.*,u.favorite,u.excluded,u.viewed_at,u.category_override FROM products p LEFT JOIN product_user_state u ON u.product_id=p.id WHERE p.id=?", (product_id,)).fetchone()
        if not row:
            raise ScoutError("PRODUCT_NOT_FOUND", "Product does not exist", 404)
        value = dict(row)
        value["effective_category"] = value["category_override"] or value["category_key"]
        source = conn.execute("SELECT c.listing_json,c.detail_json,c.detail_error FROM collection_products c JOIN runs r ON r.id=c.run_id WHERE c.product_id=? ORDER BY r.created_at DESC,r.id DESC LIMIT 1", (product_id,)).fetchone()
        value["source"] = json.loads(source["detail_json"] or source["listing_json"]) if source else None
        value["latest_detail_error"] = source["detail_error"] if source else None
        value["versions"] = [dict(r) for r in conn.execute("SELECT * FROM product_versions WHERE product_id=? ORDER BY id,revision", (product_id,))]
        value["assets"] = [dict(r) for r in conn.execute("SELECT DISTINCT a.* FROM assets a JOIN version_images i ON i.asset_id=a.id JOIN product_versions v ON v.id=i.version_id AND v.revision=i.revision WHERE v.product_id=?", (product_id,))]
        current = conn.execute("SELECT manifest_json FROM product_versions WHERE id=? AND revision=?", (value["latest_observed_version_id"], value["latest_observed_revision"])).fetchone()
        value["current_gallery"] = json.loads(current[0]) if current else None
        if current:
            gallery = value["current_gallery"]
            usable = any(x["asset_id"] for x in gallery["images"])
            value["media_state"] = "ready" if gallery["complete"] and usable else "partial" if usable else "failed"
        else:
            value["media_state"] = "failed" if value["latest_detail_error"] else "queued"
        return value
