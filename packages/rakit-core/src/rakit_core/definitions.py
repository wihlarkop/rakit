from collections.abc import Callable
from dataclasses import dataclass
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .actions import ActionDefinition, _validate_operation_transaction_policy
from .config import MachineId
from .endpoints import (
    EndpointAccessPolicy,
    EndpointInputSource,
    EndpointMethod,
    EndpointResponseKind,
)
from .permissions import PermissionRequirement
from .relationships import RelationshipDefinition
from .transactions import TransactionPolicy

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
    relationships: tuple[RelationshipDefinition, ...] = ()

    @property
    def relationship_ids(self) -> tuple[str, ...]:
        return tuple(relationship.relationship_id for relationship in self.relationships)


class PageDefinition(BaseModel):
    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    page_id: MachineId
    path: AbsolutePath
    label: str
    permission: PermissionRequirement | None = None
    input_schema: type[object] | None = None
    handler: Callable[..., object] | None = None
    template: str = "pages/page.html"
    mutating: bool = False
    transaction_policy: TransactionPolicy = TransactionPolicy.READ_ONLY

    @model_validator(mode="after")
    def _validate_page_contract(self) -> "PageDefinition":
        _validate_operation_transaction_policy(self.mutating, self.transaction_policy)
        if not self.label.strip():
            raise ValueError("Page label must not be empty")
        if not self.template.strip():
            raise ValueError("Page template must not be empty")
        if self.mutating and (self.handler is None or not callable(self.handler)):
            raise ValueError(f"Mutating page {self.page_id!r} requires a callable handler")
        return self


class EndpointDefinition(BaseModel):
    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    endpoint_id: MachineId
    path: AbsolutePath
    methods: tuple[EndpointMethod, ...]
    permission: PermissionRequirement | None = None
    input_schema: type[object] | None = None
    input_source: EndpointInputSource | None = None
    output_schema: type[object] | None = None
    access_policy: EndpointAccessPolicy = EndpointAccessPolicy.PRIVATE
    response_kind: EndpointResponseKind = EndpointResponseKind.JSON
    allow_response_escape_hatch: bool = False
    handler: Callable[..., object] | None = None
    mutating: bool = False
    transaction_policy: TransactionPolicy = TransactionPolicy.READ_ONLY

    @model_validator(mode="after")
    def _validate_endpoint_contract(self) -> "EndpointDefinition":
        _validate_operation_transaction_policy(self.mutating, self.transaction_policy)
        if EndpointMethod.POST in self.methods and not self.mutating:
            raise ValueError("POST endpoints must explicitly declare mutating behavior")
        if self.access_policy is EndpointAccessPolicy.PUBLIC and self.permission is not None:
            raise ValueError(
                "Public endpoints cannot also declare a private permission requirement"
            )
        if (
            self.response_kind is not EndpointResponseKind.JSON
            and not self.allow_response_escape_hatch
        ):
            raise ValueError("Non-JSON endpoint responses require explicit escape hatch opt-in")
        if self.response_kind is not EndpointResponseKind.JSON and self.output_schema is not None:
            raise ValueError("Non-JSON endpoint responses cannot declare a JSON output schema")
        return self


@dataclass(frozen=True)
class CompiledActionDefinition:
    definition: ActionDefinition
    permission: PermissionRequirement


@dataclass(frozen=True)
class CompiledPageDefinition:
    definition: PageDefinition
    permission: PermissionRequirement


@dataclass(frozen=True)
class CompiledEndpointDefinition:
    definition: EndpointDefinition
    permission: PermissionRequirement


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
