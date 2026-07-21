from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field

from .config import MachineId

AbsolutePath = Annotated[str, Field(pattern=r"^/")]


class ResourceDefinition(BaseModel):
    model_config = ConfigDict(frozen=True)

    resource_id: MachineId
    path: AbsolutePath
    label: str
    singular_label: str


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
