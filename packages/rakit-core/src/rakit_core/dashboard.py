"""Transport-neutral dashboard and widget contracts."""

from collections.abc import Awaitable, Callable, Mapping
from enum import StrEnum
from typing import TypeAlias

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .auth import Principal
from .config import MachineId
from .di import ServiceResolver
from .permissions import PermissionRequirement


class WidgetLoadingMode(StrEnum):
    EAGER = "eager"
    LAZY = "lazy"


class WidgetSize(StrEnum):
    SMALL = "small"
    MEDIUM = "medium"
    LARGE = "large"
    FULL = "full"


class WidgetLayout(BaseModel):
    model_config = ConfigDict(frozen=True)

    size: WidgetSize = WidgetSize.MEDIUM
    priority: int = Field(default=100, ge=0)
    min_height: int | None = Field(default=None, ge=0)


class LauncherItem(BaseModel):
    model_config = ConfigDict(frozen=True)

    launcher_id: MachineId
    label: str = Field(min_length=1)
    path: str = Field(pattern=r"^/")
    permission: PermissionRequirement | None = None
    description: str | None = None


class WidgetContext(BaseModel):
    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    widget_id: MachineId
    principal: Principal | None = None
    services: ServiceResolver | None = None


class _WidgetResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    label: str = Field(min_length=1)
    layout: WidgetLayout = Field(default_factory=WidgetLayout)
    loading: WidgetLoadingMode = WidgetLoadingMode.EAGER


class StatWidgetResult(_WidgetResult):
    value: int | float | str
    description: str | None = None


class TextWidgetResult(_WidgetResult):
    text: str


class ListWidgetItem(BaseModel):
    model_config = ConfigDict(frozen=True)

    label: str = Field(min_length=1)
    value: str | None = None
    href: str | None = Field(default=None, pattern=r"^/")


class ListWidgetResult(_WidgetResult):
    items: tuple[ListWidgetItem, ...] = ()
    empty_message: str = "No items."


class TableWidgetResult(_WidgetResult):
    columns: tuple[str, ...]
    rows: tuple[tuple[object, ...], ...] = ()
    empty_message: str = "No rows."

    @model_validator(mode="after")
    def _validate_rows(self) -> "TableWidgetResult":
        width = len(self.columns)
        if any(len(row) != width for row in self.rows):
            raise ValueError("Every dashboard table row must match the declared column count")
        return self


class TemplateWidgetResult(_WidgetResult):
    template: str = Field(min_length=1)
    context: Mapping[str, object] = Field(default_factory=dict)


class WidgetErrorResult(_WidgetResult):
    message: str = "Unable to load this widget."


WidgetResult: TypeAlias = (
    StatWidgetResult
    | TextWidgetResult
    | ListWidgetResult
    | TableWidgetResult
    | TemplateWidgetResult
    | WidgetErrorResult
)
WidgetLoader: TypeAlias = Callable[[WidgetContext], WidgetResult | Awaitable[WidgetResult]]


class WidgetDefinition(BaseModel):
    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    widget_id: MachineId
    label: str = Field(min_length=1)
    loader: WidgetLoader
    permission: PermissionRequirement | None = None
    loading: WidgetLoadingMode = WidgetLoadingMode.EAGER
    layout: WidgetLayout = Field(default_factory=WidgetLayout)
    timeout_seconds: float | None = Field(default=None, gt=0)


class DashboardDefinition(BaseModel):
    model_config = ConfigDict(frozen=True)

    dashboard_id: MachineId = "main"
    title: str = Field(min_length=1)
    widgets: tuple[MachineId, ...] = ()
    launchers: tuple[LauncherItem, ...] = ()
    max_concurrent_widgets: int = Field(default=4, ge=1, le=32)

    @model_validator(mode="after")
    def _validate_unique_ids(self) -> "DashboardDefinition":
        if len(self.widgets) != len(set(self.widgets)):
            raise ValueError("Dashboard widget ids must be unique")
        launcher_ids = [item.launcher_id for item in self.launchers]
        if len(launcher_ids) != len(set(launcher_ids)):
            raise ValueError("Dashboard launcher ids must be unique")
        return self


__all__ = [
    "DashboardDefinition",
    "LauncherItem",
    "ListWidgetItem",
    "ListWidgetResult",
    "StatWidgetResult",
    "TableWidgetResult",
    "TemplateWidgetResult",
    "TextWidgetResult",
    "WidgetContext",
    "WidgetDefinition",
    "WidgetErrorResult",
    "WidgetLayout",
    "WidgetLoader",
    "WidgetLoadingMode",
    "WidgetResult",
    "WidgetSize",
]
