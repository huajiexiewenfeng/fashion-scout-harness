from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator, model_serializer


class DTO(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)


class Discovery(DTO):
    page_size: int = Field(default=20, gt=0, le=250)
    max_pages_per_pass: int = Field(default=30, gt=0)
    passes: int = Field(default=2, gt=0, le=2)
    max_requests: int = Field(default=60, gt=0)
    max_products: int = Field(default=600, gt=0)


class Timeouts(DTO):
    connect: int = Field(default=10, gt=0)
    pool: int = Field(default=10, gt=0)
    read: int = Field(default=30, gt=0)
    write: int = Field(default=30, gt=0)
    total: int = Field(default=120, gt=0)


class Network(DTO):
    resolver_mode: Literal["system", "google_doh"] = "system"
    detail_concurrency: int = Field(default=1, gt=0)
    image_concurrency: int = Field(default=2, gt=0)
    min_interval_ms: int = Field(default=1000, gt=0)
    max_attempts: int = Field(default=3, gt=0, le=3)
    max_http_requests: int = Field(default=3000, gt=0)
    max_image_requests: int = Field(default=2400, gt=0)
    run_total_seconds: int = Field(default=3600, gt=0)
    timeouts: Timeouts = Field(default_factory=Timeouts)


class Storage(DTO):
    max_image_bytes: int = Field(default=25 * 1024**2, gt=0)
    max_pixels: int = Field(default=50_000_000, gt=0)
    run_download_bytes: int = Field(default=2 * 1024**3, gt=0)
    min_free_bytes: int = Field(default=5 * 1024**3, gt=0)
    preview_cache_bytes: int = Field(default=512 * 1024**2, gt=0)


class BrowserLimits(DTO):
    max_observations: int = Field(default=100, gt=0, le=1000)
    max_selected_assets: int = Field(default=240, gt=0, le=2400)
    max_received_bytes: int = Field(default=64 * 1024**2, gt=0)
    host_seconds: int = Field(default=3600, gt=0, le=3600)
    idle_seconds: int = Field(default=600, gt=0, le=3600)


LEGACY_BROWSER_DEFAULTS = {"max_observations": 40, "max_selected_assets": 12,
    "max_received_bytes": 64 * 1024**2, "host_seconds": 900, "idle_seconds": 120}


def effective_browser_defaults(plan_data: dict) -> dict:
    """Resolve old program defaults for future Runs; saved plans/old Runs stay intact."""
    value = dict(plan_data)
    if value.get("browser") == LEGACY_BROWSER_DEFAULTS:
        value["browser"] = BrowserLimits().model_dump(mode="json")
    return value


class DefaultPlan(DTO):
    source_mode: Literal["http", "browser"] = "http"
    browser: BrowserLimits = Field(default_factory=BrowserLimits)
    site_ids: list[str] = Field(default_factory=lambda: ["futario"], min_length=1)
    window_days: Literal[7, 14] = 14
    unknown_date_policy: Literal["include", "exclude"] = "include"
    discovery: Discovery = Field(default_factory=Discovery)
    max_details: int = Field(default=300, gt=0)
    network: Network = Field(default_factory=Network)
    storage: Storage = Field(default_factory=Storage)

    @field_validator("site_ids")
    @classmethod
    def unique_sites(cls, value: list[str]) -> list[str]:
        if len(set(value)) != len(value) or any(not x for x in value):
            raise ValueError("site_ids must be unique and nonempty")
        return value


class Overrides(DTO):
    source_mode: Literal["http", "browser"] | None = None
    browser: BrowserLimits | None = None
    site_ids: list[str] | None = Field(default=None, min_length=1)
    window_days: Literal[7, 14] | None = None
    unknown_date_policy: Literal["include", "exclude"] | None = None

    @model_validator(mode="after")
    def explicit_null_is_invalid(self):
        if any(getattr(self, key) is None for key in self.model_fields_set):
            raise ValueError("omit an override instead of passing null")
        if self.site_ids and len(set(self.site_ids)) != len(self.site_ids):
            raise ValueError("site_ids must be unique")
        return self


class CreateRun(DTO):
    request_key: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_-]+$")
    trigger: Literal["skill", "ui"]
    overrides: Overrides = Field(default_factory=Overrides)


def run_request_payload(request: CreateRun, *, legacy_browser=False) -> dict:
    """Keep the v1 null/default fingerprint exact unless new fields are explicit."""
    payload = request.model_dump(mode="json", exclude={"request_key"})
    extras = {"source_mode", "browser"} & request.overrides.model_fields_set
    if extras:
        payload["request_schema"] = 2 if legacy_browser or "browser" not in extras else 3
        if "browser" in extras:
            explicit = request.overrides.browser.model_dump(mode="json", exclude_unset=True)
            payload["overrides"]["browser"] = {**LEGACY_BROWSER_DEFAULTS, **explicit} if legacy_browser else explicit
        for key in {"source_mode", "browser"} - extras:
            payload["overrides"].pop(key)
    else:
        for key in ("source_mode", "browser"):
            payload["overrides"].pop(key)
    return payload


class Snapshot(DefaultPlan):
    plan_revision: int
    window_start: str
    window_end: str
    adapter_versions: dict[str, str]
    site_entries: dict[str, str]
    new_run_trigger: Literal["manual"] = "manual"
    discovery_baseline_complete: dict[str, bool]

    @model_serializer(mode="wrap")
    def legacy_http_shape(self, handler):
        value = handler(self)
        if self.source_mode == "http":
            value.pop("source_mode", None)
            value.pop("browser", None)
        return value


RunState = Literal["queued", "running", "interrupted", "cancelling", "cancelled",
                   "succeeded", "partial", "failed"]


class RunView(DTO):
    id: str
    state: RunState
    snapshot: Snapshot
    created_at: str
    started_at: str | None
    finished_at: str | None
    epoch: int
    attempt: int
    issue_code: str | None
    resumed_at: str | None


class CreateResult(DTO):
    run: RunView
    reused: bool
    reuse_reason: Literal["request_key", "active_run"] | None
    ignored_overrides: list[str]


class Lease(DTO):
    run_id: str
    owner: str
    epoch: int


class Outcome(DTO):
    state: Literal["succeeded", "partial", "failed"]
    valid_results: int = Field(ge=0)
    coverage_complete: bool
    required_complete: bool
    evidence_ref: str = Field(min_length=1)
    issue_code: str | None = None


# Stable downstream DTOs; implementing these protocols is T2/T3, not done in T1.
class SourceImage(DTO):
    source_image_id: str
    url: str
    ordinal: int = Field(ge=0)
    variant_ids: list[str] = Field(default_factory=list)


class SourceProduct(DTO):
    source_id: str
    url: str
    title: str
    source_published_at: str | None = None
    category_raw: str | None = None
    images: list[SourceImage] = Field(default_factory=list)
    enumeration_complete: bool = False
    handle: str = ""
    raw_published_at: str | None = None
    raw_created_at: str | None = None
    date_reason: str = "unknown"
    variants: list[dict] = Field(default_factory=list)
    options: list[dict | str] = Field(default_factory=list)
    capability_notes: list[dict[str, str]] = Field(default_factory=list)


class Coverage(DTO):
    promised_scopes: list[str]
    enumeration_complete: bool
    expected_count: int | None = Field(default=None, ge=0)
    missing_ids: list[str] = Field(default_factory=list)
    capability_notes: list[dict[str, str]] = Field(default_factory=list)
