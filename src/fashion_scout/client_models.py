"""Fixed client DTOs. Source text never chooses a method, URL or executable."""
from typing import Annotated, Literal
from pydantic import Field, model_validator
from .domain.models import DTO
from .api.models import EmptyRequest, StrictOverrides, UserPatch, PlanPatch
from .api.maintenance import VerifyOptions,BackupOptions,StoragePatch
from .domain.browser_source import Observation, ID as SourceId, AdapterVersion

Id = Annotated[str, Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_-]+$")]


class Configure(DTO):
    port: int = Field(default=8765, ge=1, le=65535)


class Listing(DTO):
    category: Literal['dress', 'knitwear', 'tops', 'outerwear', 'bottoms', 'sets', 'other'] | None = None
    limit: int = Field(default=40, ge=1, le=100)
    cursor: str | None = Field(default=None, max_length=2048)


class Product(DTO):
    product_id: Id
    version_id: Id | None = None
    version_revision: int | None = Field(default=None, gt=0)

    @model_validator(mode='after')
    def version(self):
        if self.version_revision is not None and self.version_id is None:
            raise ValueError('version_id required')
        return self


class Run(DTO):
    run_id: Id


class Start(DTO):
    new_intent: Literal[True]
    overrides: StrictOverrides = Field(default_factory=StrictOverrides)

    @model_validator(mode='before')
    @classmethod
    def boolean_intent(cls, data):
        if isinstance(data, dict) and type(data.get('new_intent')) is not bool:
            raise ValueError('explicit boolean required')
        return data


class RunWrite(Start, Run):
    # No caller-supplied request_key and no overrides on retry/cancel.
    overrides: None = Field(default=None, exclude=True)

    @model_validator(mode='before')
    @classmethod
    def no_overrides(cls, data):
        if isinstance(data, dict) and 'overrides' in data:
            raise ValueError('No overrides on original-run operations')
        return data


class ProductWrite(UserPatch):
    product_id: Id

    @model_validator(mode='after')
    def real_change(self):
        if not self.model_fields_set - {'product_id', 'expected_revision'}:
            raise ValueError('No changes')
        return self


class Resume(DTO):
    intent_id: Annotated[str, Field(pattern=r'^[a-f0-9]{32}$')]


class ExportCreate(Start):
    overrides: None = Field(default=None, exclude=True)

    @model_validator(mode='before')
    @classmethod
    def no_overrides(cls,data):
        if isinstance(data,dict) and 'overrides' in data:raise ValueError('Exports use frozen favorites')
        return data


class ExportQuery(DTO):
    export_id: Id


class ExportRetry(ExportCreate,ExportQuery):pass


class Verify(ExportCreate,VerifyOptions):pass
class Backup(ExportCreate,BackupOptions):pass
class MaintenanceQuery(DTO):
    maintenance_id:Id


class BrowserRun(ExportCreate, Run):
    pass


class BrowserAttach(BrowserRun):
    adapter_version: AdapterVersion | None = None

    @model_validator(mode='after')
    def adapter_not_null(self):
        if 'adapter_version' in self.model_fields_set and self.adapter_version is None:
            raise ValueError('Omit adapter_version instead of null')
        return self


class BrowserObserve(BrowserRun):
    session_id: SourceId
    observation: Observation


class BrowserUpload(BrowserRun):
    session_id: SourceId
    ticket_id: SourceId
    native_directory: str = Field(min_length=1, max_length=4096)
    manifest_path: str = Field(min_length=1, max_length=4096)
    asset_id: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_-]+$")
    source_url: str = Field(min_length=1, max_length=4096)
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    bytes: int = Field(gt=0, le=25 * 1024**2)


class BrowserFailure(BrowserRun):
    session_id: SourceId
    ticket_id: SourceId
    code: Literal['HOST_ASSET_UNAVAILABLE', 'HOST_EXPORT_FAILED', 'HOST_LIMIT_REACHED']


MODELS = {
    'browser-attach': BrowserAttach, 'browser-observe': BrowserObserve,
    'browser-upload': BrowserUpload, 'browser-status': Run,
    'browser-continue': BrowserRun, 'browser-asset-failure': BrowserFailure,
    'new': Listing, 'favorites': Listing, 'product': Product,
    'progress': Run, 'latest': EmptyRequest, 'sites': EmptyRequest,
    'default-plan': EmptyRequest, 'start': Start, 'retry': RunWrite,
    'cancel': RunWrite, 'user-state': ProductWrite, 'set-default-plan': PlanPatch,
    'status': EmptyRequest, 'ensure': EmptyRequest, 'open': EmptyRequest,
    'intents': EmptyRequest, 'resume': Resume,
    'export': ExportCreate, 'export-status': ExportQuery, 'export-retry': ExportRetry,
    'maintenance': EmptyRequest, 'storage': EmptyRequest,
    'verify':Verify,'backup':Backup,'maintenance-status':MaintenanceQuery,'set-storage':StoragePatch,
}
