"""Explicit browser sources verified through normal-page DOM, never arbitrary hosts."""
from dataclasses import dataclass
import re
from urllib.parse import urlsplit


@dataclass(frozen=True)
class BrowserSite:
    id: str
    name: str
    entry: str
    product_host: str
    adapter_version: str
    image_prefixes: tuple[tuple[str, str], ...]

    def product_id(self, source_id: str) -> str:
        return self.id + "-" + source_id

    def accepts_product(self, url: str, handle: str | None = None) -> bool:
        parts = ordinary_url(url)
        prefixes = ("/products/", urlsplit(self.entry).path + "/products/")
        paths_match = (parts.path in tuple(prefix + handle for prefix in prefixes) if handle
                       else any(re.fullmatch(re.escape(prefix) + r"[A-Za-z0-9_-]+", parts.path) for prefix in prefixes))
        return parts.hostname == self.product_host and bool(paths_match)

    def accepts_image(self, url: str) -> bool:
        parts = ordinary_url(url)
        return any(parts.hostname == host and parts.path.startswith(prefix)
                   for host, prefix in self.image_prefixes)

    def accepts_listing(self, url: str, page_number: int) -> bool:
        parts, entry = ordinary_url(url), urlsplit(self.entry)
        if parts.hostname != self.product_host or parts.path != entry.path:
            return False
        if not parts.query:
            # Futario's observed Load More changes the DOM at the same URL.
            return self.id == "futario" or page_number == 1
        match = re.fullmatch(r"page=([1-9][0-9]{0,3})", parts.query)
        return bool(match and int(match[1]) <= 1000 and int(match[1]) == page_number)


def ordinary_url(value: str):
    parts = urlsplit(value)
    if (len(value) > 4096 or parts.scheme != "https" or parts.username or parts.password
            or parts.port not in (None, 443) or parts.fragment or "\\" in value
            or any(ord(c) < 32 for c in value)):
        raise ValueError("Unexpected source URL")
    return parts


# Futario's Shopify store path is from its observed T2 pageAssets image URL.
# New sites expose first-party CDN images; unverified shared/marketing CDNs stay closed.
BROWSER_SITES = {
    "futario": BrowserSite("futario", "Futario", "https://futario.com/collections/new-in",
        "futario.com", "futario-browser-host-v1",
        (("futario.com", "/cdn/shop/files/"), ("futario.com", "/cdn/shop/products/"),
         ("cdn.shopify.com", "/s/files/1/0600/7672/0193/"))),
    "rihoas": BrowserSite("rihoas", "RIHOAS", "https://www.rihoas.com/collections/new-in-dresses",
        "www.rihoas.com", "rihoas-browser-host-v1", (("www.rihoas.com", "/cdn/shop/files/"),)),
    "simpleretro": BrowserSite("simpleretro", "SimpleRetro", "https://www.simpleretro.com/collections/newest-products",
        "www.simpleretro.com", "simpleretro-browser-host-v1", (("www.simpleretro.com", "/cdn/shop/files/"),)),
}


def product_site(url: str, handle: str | None = None) -> BrowserSite:
    for site in BROWSER_SITES.values():
        if site.accepts_product(url, handle):
            return site
    raise ValueError("Product URL is outside the verified site registry")


def snapshot_site(snapshot) -> BrowserSite:
    if len(snapshot.site_ids) != 1 or snapshot.site_ids[0] not in BROWSER_SITES:
        raise ValueError("Browser Run requires one registered site")
    site = BROWSER_SITES[snapshot.site_ids[0]]
    if (snapshot.adapter_versions.get(site.id) != site.adapter_version or
            snapshot.site_entries.get(site.id) != site.entry):
        raise ValueError("Frozen site entry or browser adapter does not match")
    return site
