from contextlib import AbstractAsyncContextManager
from enum import StrEnum
from typing import TYPE_CHECKING, Protocol

from rakit_core.events import EventPublisher

if TYPE_CHECKING:
    from rakit_core.operations import OperationContext


class TransactionPolicy(StrEnum):
    """How an operation-scoped unit of work reaches a durable outcome."""

    AUTO = "auto"
    READ_ONLY = "read_only"
    DISABLED = "disabled"
    MANUAL = "manual"


class OperationUnitOfWork(Protocol):
    """A backend-neutral operation-owned unit of work.

    The root operation lifecycle opens one of these for AUTO/MANUAL mutating
    operations, exposes it on ``OperationContext.unit_of_work``, and lets the
    UoW implementation own the durable outcome (commit/rollback and the
    deferred post-commit event lifecycle).  After a driver commit succeeds,
    adapters mark ``OperationContext.durable_commit_completed`` before any
    post-commit callback that may fail.  No persistence type appears here.
    """

    policy: TransactionPolicy

    async def mark_success(self) -> None: ...

    async def commit(self) -> None: ...

    async def rollback(self, cause: BaseException | None = None) -> None: ...


class OperationUnitOfWorkFactory(Protocol):
    """Opens a backend-neutral root unit of work for one operation.

    Persistence plugins (e.g. the SQLAlchemy plugin) register one
    APPLICATION-scoped instance of this contract; core and web never know
    which backend produced it.
    """

    def open(
        self,
        *,
        policy: TransactionPolicy,
        event_publisher: EventPublisher | None,
        operation_context: "OperationContext",
    ) -> AbstractAsyncContextManager[OperationUnitOfWork]: ...
