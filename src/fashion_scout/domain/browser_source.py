"""Facts from a foreground host. Qualification and completion remain Worker decisions."""
from typing import Annotated, Literal
from pydantic import Field, field_validator, model_validator
from .models import DTO
from .sites import BROWSER_SITES, ordinary_url, product_site

ADAPTER_VERSION = "futario-browser-host-v1"
AdapterVersion = Literal["futario-browser-host-v1", "rihoas-browser-host-v1", "simpleretro-browser-host-v1"]
SCOPE = "browser.gallery"
ID = Annotated[str, Field(pattern=r"^[a-f0-9]{32}$")]
KEY = Annotated[str, Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_-]+$")]


def source_url(value, *, image=False):
    ordinary_url(value)
    if image:
        if not any(site.accepts_image(value) for site in BROWSER_SITES.values()):
            raise ValueError("Image is outside verified gallery CDN paths")
    else:
        product_site(value)
    return value


class BrowserProduct(DTO):
    source_id: str = Field(pattern=r"^[0-9]{1,32}$")
    handle: str = Field(min_length=1, max_length=240, pattern=r"^[A-Za-z0-9_-]+$")
    url: str
    title: str = Field(min_length=1, max_length=2000)

    @model_validator(mode="after")
    def identity(self):
        product_site(self.url, self.handle)
        return self


class GalleryImage(DTO):
    source_image_id: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_-]+$")
    url: str
    ordinal: int = Field(ge=0, le=2399)

    @field_validator("url")
    @classmethod
    def bounded_url(cls, value):
        return source_url(value, image=True)


class Listing(DTO):
    kind: Literal["listing"]
    page_url: str
    pass_number: int = Field(ge=1, le=2)
    page_number: int = Field(ge=1, le=1000)
    terminal: bool
    products: list[BrowserProduct] = Field(max_length=600)

    @model_validator(mode="after")
    def unique(self):
        site = next((s for s in BROWSER_SITES.values() if s.accepts_listing(self.page_url, self.page_number)), None)
        if site is None or any(not site.accepts_product(p.url, p.handle) for p in self.products):
            raise ValueError("Listing products must belong to its registered site")
        if len({p.source_id for p in self.products}) != len(self.products):
            raise ValueError("Duplicate product identity")
        return self


class Detail(DTO):
    kind: Literal["detail"]
    product: BrowserProduct
    images: list[GalleryImage] = Field(max_length=2400)
    gallery_end_observed: bool
    expected_count: int | None = Field(default=None, ge=0, le=2400)
    observed_options: list[str] = Field(default_factory=list, max_length=100)

    @model_validator(mode="after")
    def unique(self):
        site = product_site(self.product.url, self.product.handle)
        if any(not site.accepts_image(i.url) for i in self.images):
            raise ValueError("Gallery image belongs to a different site")
        for values in ({i.source_image_id for i in self.images}, {i.url for i in self.images},
                       {i.ordinal for i in self.images}):
            if len(values) != len(self.images):
                raise ValueError("Gallery identities, URLs and ordinals must be distinct")
        return self


class Finish(DTO):
    kind: Literal["finish"]


Observation = Annotated[Listing | Detail | Finish, Field(discriminator="kind")]


class Attach(DTO):
    request_key: KEY
    adapter_version: AdapterVersion = ADAPTER_VERSION


class Observe(DTO):
    request_key: KEY
    session_id: ID
    observation: Observation


class AssetFailure(DTO):
    request_key: KEY
    session_id: ID
    code: Literal["HOST_ASSET_UNAVAILABLE", "HOST_EXPORT_FAILED", "HOST_LIMIT_REACHED"]


class Continue(DTO):
    request_key: KEY
