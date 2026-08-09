"""Backend-neutral mutation plans and resource lifecycle events."""

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Literal

from rakit_core.events import DomainEvent
from rakit_core.identity import RecordIdentity


def _freeze(values: Mapping[str, Any]) -> Mapping[str, Any]:
    return MappingProxyType(dict(values))


@dataclass(frozen=True)
class ResourceMutationPlan:
    operation: Literal["create", "update"]
    values: Mapping[str, Any]
    identity: RecordIdentity | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "values", _freeze(self.values))


@dataclass(frozen=True)
class MutationResult:
    identity: RecordIdentity
    record: object


@dataclass(frozen=True)
class ResourceCreated(DomainEvent):
    identity: RecordIdentity


@dataclass(frozen=True)
class ResourceUpdated(DomainEvent):
    identity: RecordIdentity
    changed_fields: tuple[str, ...]
