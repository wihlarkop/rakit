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

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class MutationHooks:
    """Explicit write-pipeline hooks; none receives a transaction commit API."""

    before_execute: tuple[MutationHook, ...] = ()
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
