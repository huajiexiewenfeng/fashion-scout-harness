"""Futario public Shopify JSON contract. Source strings are data, never instructions."""
import hashlib
import re
from datetime import datetime, timezone
from urllib.parse import urljoin
from fashion_scout.domain import ScoutError
from fashion_scout.domain.models import SourceImage, SourceProduct
from fashion_scout.services.runs import digest
from fashion_scout.media.http import validate_url

ENTRY = "https://futario.com/collections/new-in"
VERSION = "futario-json-v1"
IMAGE_HOSTS = frozenset({"futario.com", "cdn.shopify.com"})


def parse_date(raw, window_end):
    if not isinstance(raw, str):
        return None, "missing"
    try:
        value = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        end = datetime.fromisoformat(window_end.replace("Z", "+00:00"))
        if value.tzinfo is None:
            return None, "no_timezone"
        value = value.astimezone(timezone.utc)
        if value > end:
            return None, "future"
        return value.isoformat().replace("+00:00", "Z"), "source_published_at"
    except ValueError:
        return None, "invalid"


def category(raw):
    value = (raw or "").lower()
    for key, words in (("dress", ("dress",)), ("outerwear", ("coat", "jacket", "blazer")),
                       ("knitwear", ("knit", "cardigan", "sweater")), ("tops", ("top", "shirt", "blouse")),
                       ("bottoms", ("skirt", "pant", "trouser", "jeans")), ("sets", ("set",))):
        if any(word in value for word in words):
            return key
    return "other"


def normalize(data, window_end, detail=False):
    if (not isinstance(data, dict) or not isinstance(data.get("id"), (int, str))
            or isinstance(data.get("id"), bool) or not isinstance(data.get("title"), str)
            or not isinstance(data.get("handle"), str) or not re.fullmatch(r"[a-zA-Z0-9_-]+", data["handle"])):
        raise ScoutError("SOURCE_STRUCTURE_CHANGED", "Product identity contract changed")
    raw_date = data.get("published_at")
    parsed, reason = parse_date(raw_date, window_end)
    variants = data.get("variants", [])
    if not isinstance(variants, list) or any(not isinstance(x, dict) or not isinstance(x.get("id"), (int,str)) for x in variants):
        raise ScoutError("SOURCE_STRUCTURE_CHANGED", "Variants contract changed")
    options = data.get("options", [])
    if not isinstance(options, list) or any(not isinstance(x, (str,dict)) for x in options):
        raise ScoutError("SOURCE_STRUCTURE_CHANGED", "Options contract changed")
    notes = [{"scope": "description_media", "status": "unknown"},
             {"scope": "video", "status": "unsupported"},
             {"scope": "variant_completeness", "status": "unknown" if len(variants) >= 250 else "source_list_only"}]
    images = []
    if detail:
        raw_images = data.get("images")
        if not isinstance(raw_images, list):
            raise ScoutError("SOURCE_STRUCTURE_CHANGED", "Missing product.images enumeration")
        media = data.get("media", [])
        if not isinstance(media, list):
            raise ScoutError("SOURCE_STRUCTURE_CHANGED", "Media contract changed")
        media_ids = {}
        for item in media:
            if isinstance(item, dict) and item.get("media_type") == "image" and isinstance(item.get("src"), str):
                media_ids[urljoin("https://futario.com", item["src"])] = str(item.get("id", ""))
        duplicate_counts = {}
        for ordinal, raw in enumerate(raw_images):
            source = raw.get("src") if isinstance(raw, dict) else raw
            if not isinstance(source, str):
                raise ScoutError("SOURCE_STRUCTURE_CHANGED", "Image URL contract changed")
            source = urljoin("https://futario.com", source)
            validate_url(source, IMAGE_HOSTS)
            occurrence = duplicate_counts.get(source, 0)
            duplicate_counts[source] = occurrence + 1
            image_id = str(raw["id"]) if isinstance(raw, dict) and raw.get("id") else media_ids.get(source)
            image_id = image_id or "url-v1-" + hashlib.sha256((source + "#" + str(occurrence)).encode()).hexdigest()
            if isinstance(raw, dict) and not isinstance(raw.get("variant_ids", []), list):
                raise ScoutError("SOURCE_STRUCTURE_CHANGED", "Image variant relationship changed")
            related = list(map(str, raw.get("variant_ids", []))) if isinstance(raw, dict) else []
            for variant in variants:
                featured = variant.get("featured_image") or {}
                if isinstance(featured, dict) and (str(featured.get("id")) == image_id or urljoin("https://futario.com", featured.get("src", "")) == source):
                    related.append(str(variant["id"]))
            images.append(SourceImage(source_image_id=image_id, url=source, ordinal=ordinal,
                                      variant_ids=sorted(set(related))))
        if len({x.source_image_id for x in images}) != len(images):
            raise ScoutError("SOURCE_STRUCTURE_CHANGED", "Duplicate image IDs")
    raw_category = data.get("product_type", data.get("type"))
    if raw_category is not None and not isinstance(raw_category, str):
        raise ScoutError("SOURCE_STRUCTURE_CHANGED", "Category contract changed")
    return SourceProduct(source_id=str(data["id"]), handle=data["handle"],
        url="https://futario.com/products/" + data["handle"], title=data["title"],
        source_published_at=parsed, raw_published_at=raw_date if isinstance(raw_date, str) else None,
        raw_created_at=data.get("created_at") if isinstance(data.get("created_at"), str) else None,
        date_reason=reason, category_raw=raw_category, images=images,
        variants=variants, options=options, enumeration_complete=detail, capability_notes=notes)


class Futario:
    def __init__(self, http, snapshot):
        self.http, self.snapshot = http, snapshot
        if snapshot.site_entries.get("futario") != ENTRY:
            raise ScoutError("SOURCE_ENTRY_MISMATCH", "Only the verified New In entry is supported")
        if snapshot.adapter_versions.get("futario") != VERSION:
            raise ScoutError("ADAPTER_VERSION_MISMATCH", "Run requires a different adapter version")

    def capabilities(self):
        return {"adapter_version": VERSION, "discovery_method": "collection/products.json",
                "promised_scopes": ["product.images"], "outside_scope": ["video", "description_media"]}

    def discover(self, page):
        limit = self.snapshot.discovery.page_size
        url = ENTRY + f"/products.json?limit={limit}&page={page}"
        data = self.http.json(url)
        if not isinstance(data, dict) or not isinstance(data.get("products"), list):
            raise ScoutError("SOURCE_STRUCTURE_CHANGED", "Collection products contract changed")
        products = [normalize(x, self.snapshot.window_end) for x in data["products"]]
        if len(products) > limit or len({p.source_id for p in products}) != len(products):
            raise ScoutError("SOURCE_STRUCTURE_CHANGED", "Unexpected page size or duplicate identities")
        ids = [p.source_id for p in products]
        return {"products": products, "ids": ids, "signature": digest(sorted(ids)),
                "ordered_signature": digest(ids), "terminal": len(products) < limit, "url": url}

    def fetch_product(self, product):
        result = normalize(self.http.json(product.url + ".js", "detail"), self.snapshot.window_end, detail=True)
        if result.source_id != product.source_id:
            raise ScoutError("SOURCE_ID_MISMATCH", "Detail identity differs from discovery")
        return result
