"""A bounded cover projection. Full gallery/history validation belongs to detail."""
import json
from collections import defaultdict
from fashion_scout.domain import ScoutError
from fashion_scout.domain.models import Storage
from fashion_scout.domain.sites import BROWSER_SITES
from fashion_scout.media.images import validate_archived_cover


class CoverListing:
    def __init__(self, presentation):
        self.presentation = presentation
        self.cache = {}
        self.limits = Storage()

    def records(self, view, category, product_ids=None):
        conditions, args = [], []
        if product_ids is None:
            conditions.append("u.favorite=1" if view == "favorites" else "p.first_eligible_at IS NOT NULL AND u.excluded=0")
            if category:
                conditions.append("COALESCE(u.category_override,p.category_key)=?")
                args.append(category)
        else:
            if not product_ids:
                return {}, {}
            conditions.append("p.id IN (" + ",".join("?" for _ in product_ids) + ")")
            args.extend(product_ids)
        where = " AND ".join(conditions)
        with self.presentation.db.read() as conn:
            conn.execute("BEGIN")
            rows = [dict(r) for r in conn.execute(
                "SELECT p.*,u.favorite,u.excluded,u.viewed_at,u.category_override,u.revision AS user_revision,"
                "u.seen_version_id,u.seen_version_revision,u.seen_content_digest,"
                "v.content_digest AS available_digest,o.manifest_json AS observed_manifest,"
                "c.listing_json,c.detail_json,c.detail_error FROM products p "
                "JOIN product_user_state u ON u.product_id=p.id "
                "LEFT JOIN product_versions v ON v.id=p.latest_available_version_id AND v.revision=p.latest_available_revision "
                "LEFT JOIN product_versions o ON o.id=p.latest_observed_version_id AND o.revision=p.latest_observed_revision "
                "LEFT JOIN collection_products c ON c.product_id=p.id AND c.run_id=("
                "SELECT c2.run_id FROM collection_products c2 JOIN runs r ON r.id=c2.run_id "
                "WHERE c2.product_id=p.id ORDER BY r.created_at DESC,r.id DESC LIMIT 1) "
                "WHERE " + where + " ORDER BY (u.viewed_at IS NOT NULL),p.first_seen_at DESC,p.id ASC", args)]
            # Only the current available version is read, never historical albums.
            images = defaultdict(list)
            for image in conn.execute(
                "SELECT p.id AS product_id,i.ordinal,a.*,s.path AS root_path FROM products p "
                "JOIN product_user_state u ON u.product_id=p.id "
                "JOIN version_images i ON i.version_id=p.latest_available_version_id AND i.revision=p.latest_available_revision "
                "JOIN assets a ON a.id=i.asset_id JOIN storage_roots s ON s.id=a.root_id "
                "WHERE " + where + " ORDER BY p.id,i.ordinal,i.source_image_id", args):
                images[image["product_id"]].append(dict(image))
        return {r["id"]: r for r in rows}, images

    def cover(self, assets):
        for asset in assets:
            aid = asset["id"]
            if aid not in self.cache:
                try:
                    path = self.presentation.asset_path(asset)
                    validate_archived_cover(path, asset, self.limits.max_image_bytes, self.limits.max_pixels)
                    self.cache[aid] = {"asset_id": aid, "sha256": asset["sha256"], "verified_at": asset["verified_at"],
                        "preview_url": f"/v1/assets/{aid}?rendition=preview", "original_url": f"/v1/assets/{aid}?rendition=original"}
                except (ScoutError, OSError):
                    self.cache[aid] = None
            if self.cache[aid]:
                return self.cache[aid]
        return None

    def summary(self, row, cover):
        pid = row["id"]
        raw_source = json.loads(row["detail_json"] or row["listing_json"] or "{}")
        source = {key: raw_source.get(key) for key in ("source_id", "handle", "title", "url", "category_raw", "source_published_at", "date_reason")}
        observed = json.loads(row["observed_manifest"] or "{}")
        previous = (row["latest_available_version_id"], row["latest_available_revision"]) != (row["latest_observed_version_id"], row["latest_observed_revision"])
        user = {"product_id": pid, "revision": row["user_revision"], "favorite": bool(row["favorite"]),
                "excluded": bool(row["excluded"]), **{key: row[key] for key in ("viewed_at", "category_override", "seen_version_id", "seen_version_revision", "seen_content_digest")}}
        site = BROWSER_SITES.get(row["site_id"])
        # This state describes the archived observation. Full present-day album
        # readability, missing reasons and history are returned only by detail.
        media_state = "ready" if cover and observed.get("complete") and not previous else "partial" if cover else "failed" if observed or row["detail_error"] else "queued"
        return {"id": pid, "projection": "cover", "gallery_validation": "on_open", "site_id": row["site_id"],
                "site_name": site.name if site else row["site_id"], "title": source.get("title") or "暂无商品名称", "source": source,
                "first_seen_at": row["first_seen_at"], "first_eligible_at": row["first_eligible_at"],
                "effective_category": user["category_override"] or row["category_key"], "user_state": user,
                "media_state": media_state, "latest_detail_error": row["detail_error"],
                "has_material_update": bool(cover and user["viewed_at"] and row["available_digest"] and row["available_digest"] != user["seen_content_digest"]),
                "version_id": row["latest_available_version_id"] or row["latest_observed_version_id"],
                "version_revision": row["latest_available_revision"] or row["latest_observed_revision"],
                "using_previous_images": bool(cover and previous), "images": [cover] if cover else []}

    def page(self, view, category, cursor, limit):
        records, assets, covers = {}, {}, {}
        def ids():
            nonlocal records, assets
            records, assets = self.records(view, category)
            selected = []
            for pid in records:
                covers[pid] = self.cover(assets.get(pid, []))
                if view == "favorites" or covers[pid]:
                    selected.append(pid)
            return selected
        page = self.presentation.snapshots.page(ids, {"view": view, "category": category, "limit": limit}, cursor, limit)
        if cursor:
            records, assets = self.records(view, category, page["ids"])
        items = []
        for pid in page["ids"]:
            if pid not in records:
                continue
            cover = covers[pid] if pid in covers else self.cover(assets.get(pid, []))
            if cover or view == "favorites":
                items.append(self.summary(records[pid], cover))
        return {**{key: value for key, value in page.items() if key != "ids"}, "items": items}
