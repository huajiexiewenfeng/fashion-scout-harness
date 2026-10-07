"""Production collection executor. Construction/health/startup never creates a Run."""
import json
from fashion_scout.adapters.futario import Futario, IMAGE_HOSTS
from fashion_scout.db.archive import Archive
from fashion_scout.domain import Outcome, ScoutError
from fashion_scout.domain.models import SourceProduct
from fashion_scout.media.http import SafeHTTP
from fashion_scout.media.images import disk_gate, validate_image
from fashion_scout.services.catalog import Catalog

FATAL = {"STALE_LEASE", "CANCEL_REQUESTED", "DATABASE_BUSY", "ARCHIVE_ROOT_MISMATCH", "ARCHIVE_ROOT_UNAVAILABLE"}
BUDGET = {"RUN_TIME_BUDGET", "REQUEST_BUDGET", "DISCOVERY_BUDGET", "DETAIL_BUDGET", "IMAGE_REQUEST_BUDGET", "DOWNLOAD_BUDGET", "DISK_RESERVE"}


class Collector:
    def __init__(self, context, transport_factory=None, sleep=None):
        self.ctx, self.runs, self.lease, self.paths = context, context.runs, context.lease, context.paths
        self.catalog = Catalog(self.runs, self.lease, self.paths, context.collection_started)
        self.snapshot = self.catalog.snapshot
        kwargs = {"sleep": sleep} if sleep is not None else {}
        self.http = SafeHTTP(self.snapshot.network, IMAGE_HOSTS, checkpoint=context.checkpoint,
            request_charge=self.catalog.request_charge, byte_charge=self.catalog.bytes_charge,
            response_record=self.catalog.response_record,
            source_hosts={"futario.com"},
            transport_factory=transport_factory, **kwargs)
        self.adapter = Futario(self.http, self.snapshot)
        self.archive = Archive(self.paths, self.runs)

    def discover(self):
        with self.runs.db.read() as conn:
            previous = conn.execute("SELECT discovery_complete,discovery_json FROM collection_runs WHERE run_id=?", (self.lease.run_id,)).fetchone()
        if previous["discovery_complete"]:
            return json.loads(previous["discovery_json"])
        limits = self.snapshot.discovery
        all_ids = {SourceProduct.model_validate_json(r["listing_json"]).source_id for r in self.catalog.rows()}
        sets, ended, reasons = [], [], []
        for pass_number in range(1, limits.passes + 1):
            seen, signatures, terminal = set(), set(), False
            for page_number in range(1, limits.max_pages_per_pass + 1):
                self.ctx.checkpoint()
                try:
                    page = self.adapter.discover(page_number)
                except ScoutError as exc:
                    if exc.code in FATAL:
                        raise
                    reasons.append(exc.code)
                    self.catalog.issue(exc.code, f"discovery:{pass_number}:{page_number}")
                    break
                self.catalog.page(pass_number, page_number, page)
                ids = set(page["ids"])
                if ids and (page["signature"] in signatures or ids & seen):
                    reasons.append("DISCOVERY_REPEAT")
                    break
                signatures.add(page["signature"])
                for product in page["products"]:
                    if product.source_id not in all_ids and len(all_ids) >= limits.max_products:
                        reasons.append("PRODUCT_BUDGET")
                        break
                    all_ids.add(product.source_id)
                    self.catalog.discover_product(product)
                else:
                    seen.update(ids)
                    if page["terminal"]:
                        terminal = True
                        break
                    continue
                break
            if not terminal:
                reasons.append("DISCOVERY_NOT_TERMINAL")
            sets.append(seen)
            ended.append(terminal)
            if not terminal:
                break
        stable = len(sets) == 2 and sets[0] == sets[1]
        if len(sets) == 2 and not stable:
            reasons.append("DISCOVERY_UNSTABLE")
        complete = len(ended) == 2 and all(ended) and stable and not reasons
        result = {"complete": complete, "passes_ended": ended, "stable_sets": stable,
                  "unique_products": len(all_ids), "reasons": sorted(set(reasons)),
                  "atomic_source_snapshot": False, "entry": self.snapshot.site_entries["futario"]}
        self.catalog.discovery_result(result)
        return result

    def image(self, pid, row):
        self.ctx.checkpoint()
        if row["state"] == "completed":
            asset_id = json.loads(row["output_json"])["asset_id"]
            with self.runs.db.read() as conn:
                asset = conn.execute("SELECT * FROM assets WHERE id=?", (asset_id,)).fetchone()
            if not asset or asset["root_id"] != self.archive.root_id:
                raise ScoutError("ARCHIVE_ROOT_MISMATCH", "Completed asset root changed")
            path = self.paths.inside_media(asset["relative_path"])
            self.archive.verify(path, asset["sha256"], asset["bytes"])
            metadata = validate_image(path, self.snapshot.storage.max_image_bytes, self.snapshot.storage.max_pixels)
        else:
            if row["state"] != "pending":
                self.catalog.image_result(pid, row["source_image_id"], code=row["error_code"] or "ITEM_RETRY_REQUIRED")
                return False
            self.runs.start_item(self.lease, row["item_id"])
            disk_gate(self.paths, self.snapshot.storage.max_image_bytes, self.snapshot.storage.min_free_bytes)
            relative = self.archive.create_temp(self.lease, row["item_id"])
            temp = self.paths.inside_media(relative)
            try:
                self.http.fetch(row["source_url"], "image", self.snapshot.storage.max_image_bytes, temp)
                metadata = validate_image(temp, self.snapshot.storage.max_image_bytes, self.snapshot.storage.max_pixels)
                final = "originals/" + metadata["sha256"][:2] + "/" + metadata["sha256"] + "." + metadata["format"].lower()
                self.ctx.checkpoint()
                journal = self.archive.stage(self.lease, row["item_id"], relative, final, metadata["sha256"], metadata["bytes"])
                asset_id = self.archive.commit(self.lease, journal)
            finally:
                # Fenced cleanup retains unpublished journal bytes and never lets
                # an old owner remove files after a new owner takes the lease.
                self.archive.cleanup_temp(self.lease, relative)
        with self.runs.db.write() as conn:
            self.runs.fence(conn, self.lease)
            conn.execute("UPDATE assets SET format=?,width=?,height=? WHERE id=?", (metadata["format"], metadata["width"], metadata["height"], asset_id))
        self.catalog.image_result(pid, row["source_image_id"], asset_id)
        return True

    def run(self):
        discovery = self.discover()
        valid, eligible, complete_count, attempted = 0, 0, 0, 0
        exhausted = False
        for row in self.catalog.rows():
            if not row["eligible"]:
                continue
            eligible += 1
            self.ctx.checkpoint()
            pid = row["product_id"]
            product = SourceProduct.model_validate_json(row["listing_json"])
            if row["detail_json"]:
                detail = SourceProduct.model_validate_json(row["detail_json"])
            else:
                if attempted >= self.snapshot.max_details or exhausted:
                    self.catalog.detail_error(pid, "DETAIL_BUDGET")
                    continue
                attempted += 1
                try:
                    detail = self.adapter.fetch_product(product)
                    self.catalog.save_detail(pid, detail)
                except ScoutError as exc:
                    if exc.code in FATAL:
                        raise
                    self.catalog.detail_error(pid, exc.code)
                    exhausted = exhausted or exc.code in BUDGET
                    continue
            self.catalog.prepare_images(pid, detail)
            for image in self.catalog.images(pid):
                if exhausted and image["state"] != "completed":
                    self.catalog.image_result(pid, image["source_image_id"], code="RUN_BUDGET")
                    continue
                try:
                    self.image(pid, image)
                except ScoutError as exc:
                    if exc.code in FATAL:
                        raise
                    self.catalog.image_result(pid, image["source_image_id"], code=exc.code)
                    self.catalog.issue(exc.code, "item:" + image["item_id"])
                    with self.runs.db.read() as conn:
                        state = conn.execute("SELECT state FROM work_items WHERE id=?", (image["item_id"],)).fetchone()[0]
                    if state == "running":
                        self.runs.fail_item(self.lease, image["item_id"], exc.code)
                    exhausted = exhausted or exc.code in BUDGET
                except OSError:
                    self.catalog.image_result(pid, image["source_image_id"], code="STORAGE_IO")
                    self.catalog.issue("STORAGE_IO", "item:" + image["item_id"])
                    raise ScoutError("STORAGE_IO", "Storage environment failed")
            version = self.catalog.freeze_version(pid, detail)
            valid += int(version["usable"])
            complete_count += int(version["complete"])
        required_complete = eligible == complete_count
        success = discovery["complete"] and required_complete
        state = "succeeded" if success else "partial" if valid else "failed"
        return Outcome(state=state, valid_results=valid, coverage_complete=discovery["complete"],
            required_complete=required_complete, evidence_ref="site_runs:" + self.lease.run_id + ":futario",
            issue_code=None if success else "COLLECTION_INCOMPLETE")


def production_executor(context):
    if context.runs.get(context.lease.run_id).snapshot.source_mode == "browser":
        from fashion_scout.adapters.futario_browser import BrowserCollector
        return BrowserCollector(context).run()
    return Collector(context).run()
