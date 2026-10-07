"""Versioned, deeply immutable input contract; no database or network dependency."""
import hashlib
import json
from typing import Annotated, Literal
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

Text = Annotated[str, Field(min_length=1, max_length=4096)]
Sha = Annotated[str, Field(pattern=r'^[0-9a-f]{64}$')]


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)


class Frozen(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True, frozen=True, revalidate_instances='always')


class Asset(Frozen):
    asset_id: Text
    root_id: Text
    relative_path: Text
    sha256: Sha
    bytes: int = Field(gt=0)
    format: Literal['PNG', 'JPEG', 'WEBP', 'GIF', 'UNKNOWN']


class ImageRef(Frozen):
    source_image_id: Text
    source_url: str = Field(max_length=16384)
    ordinal: int = Field(ge=0)
    asset_id: Text | None = None
    missing_reason: str | None = Field(default=None, max_length=4096)
    variant_ids: tuple[str, ...] = ()


class VersionKey(Frozen):
    version_id: Text
    revision: int = Field(gt=0)


class Version(VersionKey):
    images: tuple[ImageRef, ...]
    enumeration_complete: bool
    expected_count: int | None = Field(ge=0)
    enumeration_reason: str | None = Field(default=None, max_length=4096)

    @model_validator(mode='after')
    def consistent(self):
        if len({x.source_image_id for x in self.images}) != len(self.images):
            raise ValueError('Duplicate source image relation')
        if len({x.ordinal for x in self.images}) != len(self.images):
            raise ValueError('Duplicate image ordinal')
        if self.enumeration_complete:
            if self.expected_count != len(self.images):
                raise ValueError('Complete enumeration must match frozen relation count')
        elif self.expected_count is not None or not self.enumeration_reason:
            raise ValueError('Unknown enumeration requires null count and reason')
        return self


class Capability(Frozen):
    scope: Text
    status: Literal['unknown', 'unsupported', 'supported']
    reason: str = Field(max_length=4096)

    @model_validator(mode='after')
    def outside(self):
        if self.scope == 'product.images':
            raise ValueError('Required image coverage cannot be downgraded to a capability note')
        return self


class Product(Frozen):
    product_id: Text
    # Arbitrary original fields are canonical JSON text, never mutable nested dicts.
    source_json: str = Field(max_length=1_048_576)
    date_basis_json: str = Field(max_length=262144)
    latest_available: VersionKey | None
    latest_observed: VersionKey | None
    versions: tuple[Version, ...]
    capability_notes: tuple[Capability, ...] = ()

    @field_validator('source_json', 'date_basis_json')
    @classmethod
    def json_object(cls, value):
        def pairs(items):
            result = {}
            for key, item in items:
                if key in result: raise ValueError('Duplicate raw JSON key')
                result[key] = item
            return result
        result = json.loads(value, object_pairs_hook=pairs)
        if not isinstance(result, dict): raise ValueError('Original fields must be an object')
        return canonical(result)

    @model_validator(mode='after')
    def pointers(self):
        keys = {(v.version_id, v.revision) for v in self.versions}
        if len(keys) != len(self.versions): raise ValueError('Duplicate version')
        for pointer in (self.latest_available, self.latest_observed):
            if pointer and (pointer.version_id, pointer.revision) not in keys:
                raise ValueError('Version pointer outside snapshot')
        if self.latest_available:
            version = next(v for v in self.versions if (v.version_id, v.revision) ==
                           (self.latest_available.version_id, self.latest_available.revision))
            if not any(x.asset_id for x in version.images):
                raise ValueError('Available version requires an archived asset reference')
        return self


class ExportSnapshot(Frozen):
    schema_version: Literal[1] = 1
    export_id: Text
    captured_at: Text
    promised_scope: Literal['product.images'] = 'product.images'
    products: tuple[Product, ...] = Field(min_length=1, max_length=1000)
    assets: tuple[Asset, ...] = Field(max_length=10000)

    @model_validator(mode='after')
    def relations(self):
        assets = {a.asset_id for a in self.assets}
        if len(assets) != len(self.assets): raise ValueError('Duplicate asset id')
        if len({p.product_id for p in self.products}) != len(self.products):
            raise ValueError('Duplicate product id')
        referenced = {i.asset_id for p in self.products for v in p.versions for i in v.images if i.asset_id}
        if assets != referenced:
            raise ValueError('All and only referenced archived assets must be frozen')
        if sum(len(v.images) for p in self.products for v in p.versions) > 100000:
            raise ValueError('Too many image relations')
        return self

    @classmethod
    def capture(cls, value):
        """Detach caller containers and freeze; rejects non-JSON, NaN and oversize input."""
        raw = canonical(value.model_dump(mode='json') if isinstance(value, cls) else value)
        if len(raw.encode('utf-8')) > 16 * 1024**2:
            raise ValueError('Snapshot metadata exceeds 16 MiB')
        return cls.model_validate_json(raw)

    @property
    def digest(self):
        return hashlib.sha256(canonical(self.model_dump(mode='json')).encode('utf-8')).hexdigest()


class ScopedVersion(Version):
    coverage_scope: Literal['product.images', 'browser.gallery']


class ScopedCapability(Frozen):
    scope: Text
    status: Literal['unknown', 'unsupported', 'supported']
    reason: str = Field(max_length=4096)


class ScopedProduct(Product):
    versions: tuple[ScopedVersion, ...]
    capability_notes: tuple[ScopedCapability, ...] = ()

    @model_validator(mode='after')
    def required_scope(self):
        current = next((v for v in self.versions if self.latest_observed and
                        (v.version_id,v.revision)==(self.latest_observed.version_id,self.latest_observed.revision)),None)
        if current and any(n.scope==current.coverage_scope for n in self.capability_notes):
            raise ValueError('Required current scope cannot be replaced by a capability note')
        return self


class ExportSnapshotV2(ExportSnapshot):
    schema_version: Literal[2] = 2
    promised_scope: Literal['per_version'] = 'per_version'
    products: tuple[ScopedProduct, ...] = Field(min_length=1,max_length=1000)


def capture_snapshot(value):
    if isinstance(value, ExportSnapshot):
        value=value.model_dump(mode='json')
    version=value.get('schema_version',1) if isinstance(value,dict) else None
    if version not in (1,2):
        raise ValueError('Unsupported snapshot schema')
    return (ExportSnapshotV2 if version==2 else ExportSnapshot).capture(value)


def load_snapshot(raw):
    return capture_snapshot(json.loads(raw))


class Limits(Frozen):
    max_asset_bytes: int = Field(default=64 * 1024**2, gt=0)
    max_total_bytes: int = Field(default=4 * 1024**3, gt=0)
    max_pixels: int = Field(default=50_000_000, gt=0)
    min_free_bytes: int = Field(default=64 * 1024**2, ge=0)


class ExportResult(Frozen):
    state: Literal['succeeded', 'partial', 'failed']
    snapshot_sha256: str
    path: str | None = None
    sha256: str | None = None
    bytes: int | None = None
    reused: bool = False
    missing_count: int = 0
    unknown_count: int = 0
    error_code: str | None = None
