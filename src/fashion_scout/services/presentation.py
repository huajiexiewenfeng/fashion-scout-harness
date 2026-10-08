"""Read-only catalog projections, bounded query snapshots and explicit user writes."""
import base64
import hashlib
import hmac
import json
import secrets
import threading
import time
from pathlib import Path

from fashion_scout.domain import ScoutError
from fashion_scout.domain.models import Storage
from fashion_scout.domain.sites import BROWSER_SITES
from fashion_scout.media.images import validate_image
from fashion_scout.services.catalog import product_detail
from fashion_scout.services.runs import canonical, digest, timestamp


class QuerySnapshots:
    def __init__(self, clock=time.time, ttl=900, capacity=128):
        self.clock, self.ttl, self.capacity = clock, ttl, capacity
        self.secret = secrets.token_bytes(32)
        self.entries, self.lock = {}, threading.Lock()

    def page(self, read_ids, filters, cursor, limit):
        with self.lock:
            now = self.clock()
            self.entries = {k: v for k, v in self.entries.items() if v["expires"] > now}
            fingerprint = digest(filters)
            if cursor:
                try:
                    payload, signature = cursor.split(".")
                    expected = hmac.new(self.secret, payload.encode(), hashlib.sha256).hexdigest()
                    if not hmac.compare_digest(expected, signature):
                        # A restart also loses the signing key; never resume a live sort.
                        raise ValueError()
                    data = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
                    if data["filter"] != fingerprint:
                        raise ScoutError("CURSOR_FILTER_CONFLICT", "筛选条件已改变，请刷新列表", 409)
                    sid, index = data["id"], data["next"]
                    entry = self.entries[sid]
                    if data["expires"] != entry["expires"] or not isinstance(index, int) or not 0 <= index <= len(entry["ids"]):
                        raise ValueError()
                except (ValueError, KeyError, TypeError, UnicodeError):
                    raise ScoutError("CURSOR_EXPIRED", "这份列表已过期，请刷新", 410) from None
            else:
                sid, index = secrets.token_hex(16), 0
                entry = {"ids": tuple(read_ids()), "expires": now + self.ttl}
                if len(self.entries) >= self.capacity:
                    self.entries.pop(next(iter(self.entries)))
                self.entries[sid] = entry
            end = min(index + limit, len(entry["ids"]))
            next_cursor = None
            if end < len(entry["ids"]):
                data = {"id": sid, "next": end, "filter": fingerprint, "expires": entry["expires"]}
                payload = base64.urlsafe_b64encode(canonical(data).encode()).decode().rstrip("=")
                next_cursor = payload + "." + hmac.new(self.secret, payload.encode(), hashlib.sha256).hexdigest()
            return {"ids": entry["ids"][index:end], "snapshot_id": sid,
                    "snapshot_expires_at": timestamp(entry["expires"]), "next_cursor": next_cursor,
                    "total": len(entry["ids"])}


class Presentation:
    def __init__(self, db, clock=time.time):
        self.db, self.clock = db, clock
        self.snapshots = QuerySnapshots(clock)

    def user(self, pid, conn=None):
        if conn is None:
            with self.db.read() as current:
                return self.user(pid, current)
        row = conn.execute("SELECT * FROM product_user_state WHERE product_id=?", (pid,)).fetchone()
        if not row:
            raise ScoutError("PRODUCT_NOT_FOUND", "未找到这款商品", 404)
        return {**dict(row), "favorite": bool(row["favorite"]), "excluded": bool(row["excluded"])}

    def patch(self, pid, change):
        values = change.model_dump(exclude_unset=True, exclude={"expected_revision"})
        with self.db.write() as conn:
            self.user(pid, conn)
            assignments = ",".join(f"{key}=?" for key in values)
            changed = conn.execute(f"UPDATE product_user_state SET {assignments},revision=revision+1 WHERE product_id=? AND revision=?",
                                   (*values.values(), pid, change.expected_revision)).rowcount
            if not changed:
                raise ScoutError("REVISION_CONFLICT", "这款商品的状态已改变，请刷新后再操作", 409)
            return self.user(pid, conn)

    @staticmethod
    def asset_path(row):
        root = Path(row["root_path"])
        relative = Path(row["relative_path"])
        if not root.is_absolute() or relative.is_absolute() or ":" in str(relative):
            raise ScoutError("ASSET_MISSING", "图片无法读取", 404)
        root = root.resolve()
        path = (root / relative).resolve()
        if not path.is_relative_to(root) or path == root or row["state"] != "verified" or not path.is_file():
            raise ScoutError("ASSET_MISSING", "图片文件缺失或不可用", 404)
        return path

    def asset(self, aid, conn=None):
        if conn is None:
            with self.db.read() as current:
                return self.asset(aid, current)
        row = conn.execute("SELECT a.*,s.path AS root_path FROM assets a JOIN storage_roots s ON s.id=a.root_id WHERE a.id=?", (aid,)).fetchone()
        if row is None:
            raise ScoutError("ASSET_MISSING", "未找到图片文件", 404)
        return dict(row), self.asset_path(row)

    def renderable_asset(self, aid, cache):
        if aid not in cache:
            try:
                row, path = self.asset(aid)
                limits = Storage()
                actual = validate_image(path, limits.max_image_bytes, limits.max_pixels)
                if (actual["sha256"] != row["sha256"] or actual["bytes"] != row["bytes"]
                        or any(row[k] not in (None, 0, "UNKNOWN", actual[k]) for k in ("format", "width", "height"))):
                    raise ScoutError("ASSET_MISSING", "图片完整性检查失败", 404)
                cache[aid] = row
            except (ScoutError, OSError):
                cache[aid] = None
        if cache[aid] is None:
            raise ScoutError("ASSET_MISSING", "图片无法读取", 404)
        return cache[aid]

    def has_renderable_image(self, pid, cache):
        with self.db.read() as conn:
            assets = [r[0] for r in conn.execute(
                "SELECT i.asset_id FROM products p JOIN version_images i ON "
                "i.version_id=p.latest_available_version_id AND i.revision=p.latest_available_revision "
                "WHERE p.id=? AND i.asset_id IS NOT NULL ORDER BY i.ordinal", (pid,))]
        for aid in assets:
            try:
                self.renderable_asset(aid, cache)
                return True
            except ScoutError:
                continue
        return False

    def available_images(self, manifest, cache=None):
        cache = {} if cache is None else cache
        result, missing = [], []
        for item in manifest.get("images", []):
            aid = item.get("asset_id")
            try:
                if not aid:
                    raise ScoutError("ASSET_MISSING", "", 404)
                row = self.renderable_asset(aid, cache)
                result.append({"asset_id": aid, "sha256": row["sha256"], "verified_at": row["verified_at"],
                               "preview_url": f"/v1/assets/{aid}?rendition=preview",
                               "original_url": f"/v1/assets/{aid}?rendition=original"})
            except (ScoutError, OSError):
                missing.append({"source_image_id": item["source_image_id"], "source_url": item["url"],
                                "reason": item.get("error_code") or "ASSET_MISSING", "retryable": True})
        return result, missing

    def detail(self, pid, version_id=None, revision=None, *, asset_cache=None):
        asset_cache = {} if asset_cache is None else asset_cache
        raw = product_detail(self.db, pid)
        user = self.user(pid)
        versions = raw["versions"]
        selected_id = version_id or raw["latest_available_version_id"] or raw["latest_observed_version_id"]
        selected_revision = revision if version_id else (raw["latest_available_revision"] or raw["latest_observed_revision"])
        matches = [v for v in versions if v["id"] == selected_id and (selected_revision is None or v["revision"] == selected_revision)]
        selected = max(matches, key=lambda v: v["revision"]) if matches else None
        if version_id and selected is None:
            raise ScoutError("VERSION_NOT_FOUND", "未找到这份历史图集", 404)
        manifest = json.loads(selected["manifest_json"]) if selected else {}
        images, missing = self.available_images(manifest, asset_cache)
        latest = raw["current_gallery"] or {}
        current_images, current_missing = self.available_images(latest, asset_cache)
        latest_available = next((v for v in versions if v["id"] == raw["latest_available_version_id"] and v["revision"] == raw["latest_available_revision"]), None)
        available_manifest = json.loads(latest_available["manifest_json"]) if latest_available else {}
        available, _ = self.available_images(available_manifest, asset_cache)
        # A missing local file is a delivery failure, not a newly observed content set.
        # Use the immutable verified version identity; only display an update when readable images exist.
        content_digest = latest_available["content_digest"] if available and latest_available else None
        source = raw["source"] or {}
        media_state = raw["media_state"]
        if latest:
            media_state = "ready" if latest.get("complete") and current_images and not current_missing else "partial" if current_images else "failed"
        site = BROWSER_SITES.get(raw["site_id"])
        return {"id": pid, "site_id": raw["site_id"], "site_name": site.name if site else raw["site_id"],
                "title": source.get("title") or "暂无商品名称", "source": source,
                "first_seen_at": raw["first_seen_at"], "first_eligible_at": raw["first_eligible_at"],
                "effective_category": user["category_override"] or raw["category_key"],
                "user_state": user, "media_state": media_state, "latest_detail_error": raw["latest_detail_error"],
                "has_material_update": bool(user["viewed_at"] and content_digest and content_digest != user["seen_content_digest"]),
                "latest_available_version_id": raw["latest_available_version_id"], "latest_available_revision": raw["latest_available_revision"],
                "latest_complete_version_id": raw["latest_complete_version_id"], "latest_complete_revision": raw["latest_complete_revision"],
                "latest_observed_version_id": raw["latest_observed_version_id"], "latest_observed_revision": raw["latest_observed_revision"],
                "version_id": selected["id"] if selected else None, "version_revision": selected["revision"] if selected else None,
                "images": images, "album": self.album(manifest, images, missing),
                "latest_observed_album": self.album(latest, current_images, current_missing),
                "using_previous_images": bool(selected and (selected["id"], selected["revision"]) != (raw["latest_observed_version_id"], raw["latest_observed_revision"])),
                "versions": [{"id": v["id"], "revision": v["revision"], "content_digest": v["content_digest"]} for v in versions]}

    @staticmethod
    def album(manifest, images, missing):
        return {"expected_count": manifest.get("expected_count") if manifest.get("enumeration_complete") else None,
                "stored_count": len(images), "missing": missing,
                "coverage_scope": manifest.get("promised_scopes", ["product.images"]),
                "coverage_complete": bool(manifest.get("complete") and not missing),
                "verified_at": min((x["verified_at"] for x in images), default=None), "capability_notes": manifest.get("capability_notes", [])}

    def listing(self, view, category, cursor, limit):
        from fashion_scout.services.listing import CoverListing
        return CoverListing(self).page(view, category, cursor, limit)

    def view_event(self, pid, event):
        with self.db.write() as conn:
            self.user(pid, conn)
            prior = conn.execute("SELECT * FROM view_events WHERE event_id=?", (event.event_id,)).fetchone()
            if prior:
                if (prior["product_id"], prior["version_id"], prior["version_revision"]) != (pid, event.version_id, event.version_revision):
                    raise ScoutError("EVENT_ID_CONFLICT", "浏览事件已用于另一份图集", 409)
                return {"reused": True, "user_state": self.user(pid, conn)}
            version = conn.execute("SELECT * FROM product_versions WHERE id=? AND revision=? AND product_id=?", (event.version_id, event.version_revision, pid)).fetchone()
            if not version:
                raise ScoutError("VERSION_NOT_FOUND", "未找到这份图集", 404)
            hashes, readable = set(), False
            for row in conn.execute("SELECT DISTINCT asset_id FROM version_images WHERE version_id=? AND revision=? AND asset_id IS NOT NULL", (event.version_id, event.version_revision)):
                metadata = conn.execute("SELECT sha256 FROM assets WHERE id=?", (row[0],)).fetchone()
                if metadata:
                    hashes.add(metadata["sha256"])
                try:
                    asset, path = self.asset(row[0], conn)
                    with path.open("rb") as stream:
                        if hashlib.file_digest(stream, "sha256").hexdigest() == asset["sha256"]:
                            readable = True
                except (ScoutError, OSError):
                    continue
            if not readable:
                raise ScoutError("NO_RENDERABLE_IMAGE", "没有可读取的图片，未记录已看", 409)
            content_digest = digest({"sha256": sorted(hashes)})
            if content_digest != version["content_digest"]:
                raise ScoutError("VERSION_CONTENT_CONFLICT", "图集内容记录不一致，未记录已看", 409)
            now = timestamp(self.clock())
            conn.execute("INSERT INTO view_events VALUES (?,?,?,?,?)", (event.event_id, pid, event.version_id, event.version_revision, now))
            conn.execute("UPDATE product_user_state SET viewed_at=?,seen_version_id=?,seen_version_revision=?,seen_content_digest=? WHERE product_id=?",
                         (now, event.version_id, event.version_revision, content_digest, pid))
            return {"reused": False, "user_state": self.user(pid, conn)}
