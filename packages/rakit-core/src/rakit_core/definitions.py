from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field

from .config import MachineId

AbsolutePath = Annotated[str, Field(pattern=r"^/")]


class ResourceFieldPolicy(BaseModel):
    """Immutable, backend-neutral read-field policy for one resource."""

    model_config = ConfigDict(frozen=True)

    list_fields: tuple[str, ...] = ()
    detail_fields: tuple[str, ...] = ()
    filter_fields: tuple[str, ...] = ()
    search_fields: tuple[str, ...] = ()
    sort_fields: tuple[str, ...] = ()


class ResourceDefinition(BaseModel):
    model_config = ConfigDict(frozen=True)

    resource_id: MachineId
    path: AbsolutePath
    label: str
    singular_label: str
    field_policy: ResourceFieldPolicy = Field(default_factory=ResourceFieldPolicy)


class PageDefinition(BaseModel):
    model_config = ConfigDict(frozen=True)

    page_id: MachineId
    path: AbsolutePath
    label: str


class EndpointDefinition(BaseModel):
    model_config = ConfigDict(frozen=True)

    endpoint_id: MachineId
    path: AbsolutePath
    methods: tuple[str, ...]


class ActionDefinition(BaseModel):
    model_config = ConfigDict(frozen=True)

    action_id: MachineId
    label: str
    scope: str


class RouteDefinition(BaseModel):
    model_config = ConfigDict(frozen=True)

    route_name: str
    methods: tuple[str, ...]
    path: AbsolutePath
    owner_id: MachineId
    framework_owned: bool = False
    """Whether Rakit itself owns this route.

    Only framework-owned routes may occupy a reserved path prefix (see
    `compiler.RESERVED_PATH_PREFIXES`). This is a distinct field rather than
    an `owner_id == "rakit"` convention precisely so it cannot be forged: a
    `ResourceAdmin` whose `resource_id` happens to be `"rakit"` would
    otherwise inherit permission to claim `/auth/login`.
    """
