from typing import Literal
from pydantic import Field, model_validator, field_validator
from fashion_scout.domain.models import DTO, CreateRun, Overrides, Discovery, Network, Storage, BrowserLimits


class StrictOverrides(Overrides):
    @field_validator("window_days", mode="before")
    @classmethod
    def integer_days(cls, value):
        if type(value) is not int:
            raise ValueError("window_days must be an integer")
        return value


class CreateRunRequest(CreateRun):
    overrides: StrictOverrides = Field(default_factory=StrictOverrides)


class Operation(DTO):
    request_key: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_-]+$")


class Retry(Operation):
    scope: Literal["failed"] = "failed"
    item_ids: list[str] | None = Field(default=None, min_length=1)

    @model_validator(mode="after")
    def valid_items(self):
        if "item_ids" in self.model_fields_set and (self.item_ids is None or any(not x or len(x) > 128 for x in self.item_ids) or len(set(self.item_ids)) != len(self.item_ids)):
            raise ValueError("Omit item_ids or provide distinct nonempty IDs")
        return self


class PlanPatch(DTO):
    source_mode: Literal["http", "browser"] | None = None
    browser: BrowserLimits | None = None
    expected_revision: int = Field(gt=0)
    site_ids: list[str] | None = Field(default=None, min_length=1)
    window_days: Literal[7, 14] | None = None
    unknown_date_policy: Literal["include", "exclude"] | None = None
    discovery: Discovery | None = None
    max_details: int | None = Field(default=None, gt=0)
    network: Network | None = None
    storage: Storage | None = None

    @field_validator("window_days", mode="before")
    @classmethod
    def integer_days(cls, value):
        if type(value) is not int:
            raise ValueError("window_days must be an integer")
        return value

    @model_validator(mode="after")
    def changes(self):
        fields = self.model_fields_set - {"expected_revision"}
        if not fields or any(getattr(self, f) is None for f in fields):
            raise ValueError("Provide non-null plan changes")
        return self


class UserPatch(DTO):
    expected_revision: int = Field(gt=0)
    favorite: bool | None = None
    excluded: bool | None = None
    category_override: Literal["dress", "tops", "knitwear", "bottoms", "outerwear", "sets", "other"] | None = None

    @model_validator(mode="after")
    def changes(self):
        fields = self.model_fields_set - {"expected_revision"}
        if not fields or any(getattr(self, f) is None for f in fields - {"category_override"}):
            raise ValueError("Provide changes; only category_override may be null")
        return self


class ViewEvent(DTO):
    event_id: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_-]+$")
    version_id: str = Field(min_length=1, max_length=128)
    version_revision: int = Field(gt=0)


class BootstrapExchange(DTO):
    code: str = Field(min_length=32, max_length=128)


class EmptyRequest(DTO):
    pass
