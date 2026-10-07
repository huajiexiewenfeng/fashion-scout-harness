"""Foreground observation consumer. No browser, cookie, source HTTP or RPC code."""
import json
import os
import time
from pydantic import TypeAdapter
from fashion_scout.db.archive import Archive
from fashion_scout.domain import Outcome, ScoutError
from fashion_scout.domain.browser_source import Observation, SCOPE
from fashion_scout.domain.models import SourceProduct, SourceImage
from fashion_scout.domain.sites import snapshot_site
from fashion_scout.media.browser_intake import BrowserIntake, receiver_dead
from fashion_scout.media.images import disk_gate, validate_image
from fashion_scout.services.browser_acquisition import BrowserAcquisition, SourceWait
from fashion_scout.services.catalog import Catalog
from fashion_scout.services.runs import digest, new_id


def product_from_dom(value, detail=None):
    notes = [
        {"scope": "product.images", "status": "unknown", "reason": "Normal page gallery does not prove the complete Shopify product.images collection"},
        {"scope": "variant_identity", "status": "unknown", "reason": "Visible option labels do not prove variant IDs or complete associations"},
        {"scope": "source_dates", "status": "unknown", "reason": "Publication and creation dates were not observable"},
        {"scope": "original_resolution", "status": "unknown", "reason": "Browser export may use a negotiated responsive rendition"},
    ]
    images = [] if detail is None else [SourceImage(**i.model_dump()) for i in detail.images]
    complete = bool(detail and detail.gallery_end_observed and detail.expected_count == len(images) and images)
    return SourceProduct(**value.model_dump(), images=images, enumeration_complete=complete,
                         date_reason="browser_dates_unobservable", capability_notes=notes,
                         options=[] if detail is None else detail.observed_options)


class BrowserCollector:
    def __init__(self, context):
        self.ctx, self.runs, self.lease, self.paths = context, context.runs, context.lease, context.paths
        self.site = snapshot_site(self.runs.get(self.lease.run_id).snapshot)
        self.catalog = Catalog(self.runs, self.lease, self.paths, context.collection_started, site_id=self.site.id)
        self.snapshot = self.catalog.snapshot
        self.source = BrowserAcquisition(self.runs)
        self.intake = BrowserIntake(self.paths, self.runs)
        self.archive = Archive(self.paths, self.runs)
        with self.runs.db.write() as conn:
            self.runs.fence(conn, self.lease)
            self.source.ensure(conn, self.lease.run_id)

    def messages(self):
        with self.runs.db.read() as conn:
            return [dict(r) for r in conn.execute("SELECT * FROM browser_messages WHERE run_id=? AND state='pending' ORDER BY sequence", (self.lease.run_id,))]

    def apply(self, message):
        observation = TypeAdapter(Observation).validate_json(message["observation_json"])
        self.source.validate_observation(self.catalog.run, observation)
        if observation.kind == "listing":
            if observation.page_number > self.snapshot.discovery.max_pages_per_pass:
                raise ScoutError("DISCOVERY_BUDGET", "Frozen page observation allowance reached")
            known = {r["product_id"] for r in self.catalog.rows()}
            facts={"signature":digest(sorted(p.source_id for p in observation.products)),
                   "ids":[p.source_id for p in observation.products],"terminal":observation.terminal,"scope":"browser.listing"}
            with self.runs.db.read() as conn:
                prior=conn.execute("SELECT evidence_json FROM collection_page_attempts WHERE run_id=? AND attempt=? AND pass=? AND page=?",
                    (self.lease.run_id,self.catalog.run.attempt,observation.pass_number,observation.page_number)).fetchone()
            if prior and json.loads(prior[0])!=facts:
                raise ScoutError("SOURCE_OBSERVATION_CONFLICT", "Listing page facts are already frozen for this attempt")
            if len(known | {self.site.product_id(p.source_id) for p in observation.products}) > self.snapshot.discovery.max_products:
                raise ScoutError("PRODUCT_BUDGET", "Frozen product allowance reached")
            for value in observation.products:
                self.catalog.discover_product(product_from_dom(value))
            self.catalog.page(observation.pass_number, observation.page_number,facts)
        elif observation.kind == "detail":
            pid = self.site.product_id(observation.product.source_id)
            rows = self.catalog.rows()
            row = next((r for r in rows if r["product_id"] == pid), None)
            if not row:
                raise ScoutError("SOURCE_LISTING_REQUIRED", "Listing must establish numeric product identity first")
            listing = SourceProduct.model_validate_json(row["listing_json"])
            # The observed collection link may redirect to /products/{handle}.
            # Both paths are registry-bound; numeric ID and handle stay frozen.
            if (listing.handle != observation.product.handle
                    or not self.site.accepts_product(listing.url, observation.product.handle)):
                raise ScoutError("SOURCE_IDENTITY_CONFLICT", "Detail identity differs from accepted listing")
            if not row["eligible"]:
                with self.runs.db.write() as conn:
                    self.runs.fence(conn, self.lease)
                    conn.execute("UPDATE browser_messages SET state='applied' WHERE id=?", (message["id"],))
                return
            product = product_from_dom(observation.product, observation)
            if row["detail_json"] and SourceProduct.model_validate_json(row["detail_json"]) != product:
                raise ScoutError("SOURCE_OBSERVATION_CONFLICT", "Run gallery observation is already frozen")
            if not row["detail_json"]:
                if sum(bool(r["detail_json"]) for r in rows) >= self.snapshot.max_details:
                    raise ScoutError("DETAIL_BUDGET", "Frozen detail observation allowance reached")
                self.catalog.save_detail(pid, product)
            self.catalog.prepare_images(pid, product)
            with self.runs.db.write() as conn:
                self.runs.fence(conn, self.lease)
                for image in conn.execute("SELECT * FROM collection_images WHERE run_id=? AND product_id=?", (self.lease.run_id, pid)).fetchall():
                    conn.execute("INSERT OR IGNORE INTO browser_assets(id,run_id,product_id,source_image_id,item_id,source_url) VALUES (?,?,?,?,?,?)",
                                 (new_id(), self.lease.run_id, pid, image["source_image_id"], image["item_id"], image["source_url"]))
        with self.runs.db.write() as conn:
            self.runs.fence(conn, self.lease)
            conn.execute("UPDATE browser_messages SET state='applied' WHERE id=?", (message["id"],))

    def image(self, ticket):
        self.ctx.checkpoint()
        with self.runs.db.read() as conn:
            item = conn.execute("SELECT * FROM work_items WHERE id=?", (ticket["item_id"],)).fetchone()
        if item["state"] == "completed":
            aid = json.loads(item["output_json"])["asset_id"]
            with self.runs.db.read() as conn:
                asset = conn.execute("SELECT * FROM assets WHERE id=?", (aid,)).fetchone()
            if not asset or asset["root_id"] != self.archive.root_id:
                raise ScoutError("ARCHIVE_ROOT_MISMATCH", "Completed image root differs")
            path = self.paths.inside_media(asset["relative_path"])
            self.archive.verify(path, asset["sha256"], asset["bytes"])
            metadata = validate_image(path, self.snapshot.storage.max_image_bytes, self.snapshot.storage.max_pixels)
        elif ticket["state"] == "received":
            self.runs.start_item(self.lease, ticket["item_id"])
            disk_gate(self.paths, self.snapshot.storage.max_image_bytes, self.snapshot.storage.min_free_bytes)
            relative = self.archive.create_temp(self.lease, ticket["item_id"])
            temp = self.paths.inside_media(relative)
            try:
                body = self.intake.path(ticket["body_path"])
                self.archive.verify(body, ticket["sha256"], ticket["bytes"])
                with body.open("rb") as incoming, temp.open("wb") as outgoing:
                    while chunk := incoming.read(65536):
                        self.ctx.checkpoint()
                        outgoing.write(chunk)
                    outgoing.flush()
                    os.fsync(outgoing.fileno())
                metadata = validate_image(temp, self.snapshot.storage.max_image_bytes, self.snapshot.storage.max_pixels)
                final = "originals/" + metadata["sha256"][:2] + "/" + metadata["sha256"] + "." + metadata["format"].lower()
                self.ctx.checkpoint()
                jid = self.archive.stage(self.lease, ticket["item_id"], relative, final, metadata["sha256"], metadata["bytes"])
                aid = self.archive.commit(self.lease, jid)
            finally:
                self.archive.cleanup_temp(self.lease, relative)
        else:
            return False
        with self.runs.db.write() as conn:
            self.runs.fence(conn, self.lease)
            conn.execute("UPDATE assets SET format=?,width=?,height=? WHERE id=?", (metadata["format"], metadata["width"], metadata["height"], aid))
            conn.execute("UPDATE browser_assets SET state='archived',issue_code=NULL WHERE id=?", (ticket["id"],))
        self.catalog.image_result(ticket["product_id"], ticket["source_image_id"], asset=aid)
        return True

    def discovery(self):
        with self.runs.db.read() as conn:
            pages = [dict(r) for r in conn.execute("SELECT * FROM collection_page_attempts WHERE run_id=? AND attempt=? ORDER BY pass,page", (self.lease.run_id, self.catalog.run.attempt))]
        sets, ended, reasons = [], [], []
        for number in (1, 2):
            current = [p for p in pages if p["pass"] == number]
            facts = [json.loads(p["evidence_json"]) for p in current]
            seen = [sid for f in facts for sid in f["ids"]]
            contiguous = [p["page"] for p in current] == list(range(1, len(current) + 1))
            terminal = bool(facts and contiguous and facts[-1]["terminal"] and not any(f["terminal"] for f in facts[:-1]))
            if len(set(seen)) != len(seen):
                reasons.append("DISCOVERY_REPEAT")
            sets.append(set(seen))
            ended.append(terminal)
        stable = sets[0] == sets[1]
        complete = all(ended) and stable and not reasons
        if not all(ended):
            reasons.append("DISCOVERY_NOT_TERMINAL")
        if not stable:
            reasons.append("DISCOVERY_UNSTABLE")
        result = {"complete": complete, "passes_ended": ended, "stable_sets": stable,
                  "unique_products": len(sets[0] | sets[1]), "reasons": reasons,
                  "atomic_source_snapshot": False, "entry": self.snapshot.site_entries[self.site.id],
                  "site_id": self.site.id,
                  "scope": "browser.listing", "media_scope": SCOPE,
                  "network_accounting": "browser_background_requests_bytes_and_peer_unknown"}
        self.catalog.discovery_result(result)
        return result

    def freeze(self):
        eligible, valid, completed = 0, 0, 0
        for row in self.catalog.rows():
            if row["eligible"]:
                eligible += 1
                if row["detail_json"]:
                    product = SourceProduct.model_validate_json(row["detail_json"])
                    result = self.catalog.freeze_version(row["product_id"], product, SCOPE)
                    valid += int(result["usable"])
                    completed += int(result["complete"])
        return eligible, valid, completed

    def run(self):
        while True:
            loop_started=time.monotonic()
            self.ctx.checkpoint()
            self.catalog.check_time_budget()
            changed = False
            for message in self.messages():
                self.ctx.checkpoint()
                try:
                    self.apply(message)
                except ScoutError as exc:
                    if exc.code in {"STALE_LEASE", "CANCEL_REQUESTED", "DATABASE_BUSY"}:
                        raise
                    self.catalog.issue(exc.code, "source-message:" + message["id"])
                    with self.runs.db.write() as conn:
                        self.runs.fence(conn, self.lease)
                        conn.execute("UPDATE browser_messages SET state='rejected',issue_code=? WHERE id=?", (exc.code, message["id"]))
                changed = True
            with self.runs.db.read() as conn:
                tickets = [dict(r) for r in conn.execute("SELECT b.*,w.state item_state FROM browser_assets b JOIN work_items w ON w.id=b.item_id WHERE b.run_id=?", (self.lease.run_id,))]
            for ticket in tickets:
                if ticket["state"] == "uploading" and receiver_dead(ticket):
                    with self.runs.db.write() as conn:
                        self.runs.fence(conn, self.lease)
                        conn.execute("UPDATE browser_assets SET state='failed',issue_code='SOURCE_UPLOAD_INTERRUPTED' WHERE id=? AND state='uploading'", (ticket["id"],))
                    continue
                if ticket["state"] == "received" or (ticket["item_state"] == "completed" and ticket["state"] != "archived"):
                    try:
                        self.image(ticket)
                    except ScoutError as exc:
                        if exc.code in {"STALE_LEASE", "CANCEL_REQUESTED", "DATABASE_BUSY", "ARCHIVE_ROOT_MISMATCH", "ARCHIVE_ROOT_UNAVAILABLE"}:
                            raise
                        self.catalog.image_result(ticket["product_id"], ticket["source_image_id"], code=exc.code)
                        self.catalog.issue(exc.code, "source-ticket:" + ticket["id"])
                        with self.runs.db.write() as conn:
                            self.runs.fence(conn, self.lease)
                            conn.execute("UPDATE browser_assets SET state='failed',issue_code=? WHERE id=?", (exc.code, ticket["id"]))
                            item_state = conn.execute("SELECT state FROM work_items WHERE id=?", (ticket["item_id"],)).fetchone()[0]
                        if item_state == "running":
                            self.runs.fail_item(self.lease, ticket["item_id"], exc.code)
                    changed = True
            if changed:
                self.freeze()
            with self.runs.db.read() as conn:
                state = conn.execute("SELECT * FROM browser_runs WHERE run_id=?", (self.lease.run_id,)).fetchone()
                pending = conn.execute("SELECT 1 FROM browser_messages WHERE run_id=? AND state='pending'", (self.lease.run_id,)).fetchone()
                uploading = conn.execute("SELECT 1 FROM browser_assets WHERE run_id=? AND state IN ('uploading','received')", (self.lease.run_id,)).fetchone()
                rejected = conn.execute("SELECT 1 FROM browser_messages WHERE run_id=? AND state='rejected'", (self.lease.run_id,)).fetchone()
            if state["finish_received"] and not pending and not uploading:
                discovery = self.discovery()
                eligible, valid, completed = self.freeze()
                observed_complete = eligible == completed and not rejected
                # A closed DOM gallery is useful, but does not prove the original
                # full product.images promise. Preserve that unknown in the Run.
                required = False
                success = False
                with self.runs.db.write() as conn:
                    self.runs.fence(conn, self.lease)
                    conn.execute("UPDATE browser_runs SET phase='finished' WHERE run_id=?", (self.lease.run_id,))
                    conn.execute("UPDATE browser_sessions SET state='closed' WHERE run_id=?", (self.lease.run_id,))
                return Outcome(state="succeeded" if success else "partial" if valid else "failed", valid_results=valid,
                               coverage_complete=discovery["complete"], required_complete=required,
                               evidence_ref="browser-source:" + self.lease.run_id,
                               issue_code="SOURCE_SCOPE_UNKNOWN" if discovery["complete"] and observed_complete else "COLLECTION_INCOMPLETE")
            if not pending and not uploading and time.time() - state["last_activity"] >= self.snapshot.browser.idle_seconds:
                self.freeze()
                self.discovery()
                raise SourceWait()
            before = time.monotonic()
            time.sleep(.1)
            self.catalog.execution_started += time.monotonic() - (before if changed else loop_started)
