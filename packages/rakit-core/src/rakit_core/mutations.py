"""Backend-neutral mutation plans and resource lifecycle events."""

import inspect
import logging
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Literal

from rakit_core.events import DomainEvent
from rakit_core.identity import RecordIdentity

MutationHook = Callable[[object], object | Awaitable[object]]
MutationOperation = Literal["create", "update", "delete"]

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class MutationAuthorization:
    """A server-derived authorization decision for one mutation operation.

    This is deliberately an explicit call argument rather than ambient state:
    the web boundary creates it only after its normal RBAC decision succeeds,
    while direct pipeline callers must consciously provide an equivalent
    authorization decision.
    """

    admin_id: str
    resource_id: str
    operation: MutationOperation
    principal_id: str
    permissions: tuple[str, ...]


@dataclass(frozen=True)
class MutationHooks:
    """Explicit write-pipeline hooks; none receives a transaction commit API."""

    normalize: tuple[MutationHook, ...] = ()
    business_validate: tuple[MutationHook, ...] = ()
    prepare: tuple[MutationHook, ...] = ()
    authorize: tuple[MutationHook, ...] = ()
    pre_event: tuple[MutationHook, ...] = ()
    before_execute: tuple[MutationHook, ...] = ()
    after_execute: tuple[MutationHook, ...] = ()
    after_flush: tuple[MutationHook, ...] = ()
    before_commit: tuple[MutationHook, ...] = ()
    after_commit: tuple[MutationHook, ...] = ()
    after_rollback: tuple[MutationHook, ...] = ()


async def run_mutation_hooks(hooks: tuple[MutationHook, ...], value: object) -> None:
    for hook in hooks:
        result = hook(value)
        if inspect.isawaitable(result):
            await result


async def run_after_commit_hooks(hooks: tuple[MutationHook, ...], value: object) -> None:
    """Run observers without converting a durable mutation back into a failure."""
    for hook in hooks:
        try:
            result = hook(value)
            if inspect.isawaitable(result):
                await result
        except Exception:
            logger.exception("Post-commit mutation hook failed; continuing.")


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
class UpdateMutationPlan:
    """The update-specific state visible to lifecycle phases."""

    identity: RecordIdentity
    current_record: object
    scalar_changes: Mapping[str, Any]
    relationship_changes: Mapping[str, Any]
    concurrency_token: str | None
    concurrency_metadata: Mapping[str, Any]
    operation: Literal["update"] = "update"

    def __post_init__(self) -> None:
        object.__setattr__(self, "scalar_changes", _freeze(self.scalar_changes))
        object.__setattr__(self, "relationship_changes", _freeze(self.relationship_changes))
        object.__setattr__(self, "concurrency_metadata", _freeze(self.concurrency_metadata))


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


@dataclass(frozen=True)
class ResourceDeleted(DomainEvent):
    identity: RecordIdentity
