"""Operation deadlines and cooperative cancellation checkpoints."""

import asyncio
import uuid
from collections.abc import Awaitable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar, Token
from dataclasses import dataclass
from time import monotonic

import anyio

from rakit_core.auth import Principal
from rakit_core.di import ServiceResolver
from rakit_core.errors import ErrorCode, RakitError
from rakit_core.events import EventPublisher


def _timeout_error() -> RakitError:
    return RakitError(
        code=ErrorCode.OPERATION_TIMEOUT,
        message="The operation exceeded its deadline.",
        status_code=504,
    )


@dataclass(frozen=True)
class Deadline:
    expires_at: float

    @classmethod
    def after(cls, seconds: float) -> "Deadline":
        if seconds <= 0:
            raise ValueError("Operation deadline must be positive")
        return cls(expires_at=monotonic() + seconds)

    @property
    def expired(self) -> bool:
        return monotonic() >= self.expires_at


class CancellationContext:
    def __init__(self) -> None:
        self._cancelled = False

    def cancel(self) -> None:
        self._cancelled = True

    def check(self, deadline: Deadline | None = None) -> None:
        if self._cancelled or (deadline is not None and deadline.expired):
            raise _timeout_error()


@dataclass(frozen=True)
class OperationContext:
    deadline: Deadline | None
    cancellation: CancellationContext
    request_id: str = ""
    operation_id: str = ""
    principal: Principal | None = None
    principal_id: str = ""
    admin_id: str = ""
    resource_id: str = ""
    operation: str = ""
    permissions: tuple[str, ...] = ()
    services: ServiceResolver | None = None
    events: EventPublisher | None = None

    def __post_init__(self) -> None:
        if self.principal is not None and not self.principal_id:
            object.__setattr__(self, "principal_id", self.principal.subject_id)

    def checkpoint(self) -> None:
        self.cancellation.check(self.deadline)


_current_operation_context: ContextVar[OperationContext | None] = ContextVar(
    "rakit_current_operation_context", default=None
)


def current_operation_context() -> OperationContext | None:
    """The request operation context, available to adapters in this task only."""
    return _current_operation_context.get()


def new_operation_id() -> str:
    """Create a backend-neutral correlation identifier for one operation."""
    return str(uuid.uuid4())


@contextmanager
def activate_operation_context(context: OperationContext) -> Iterator[None]:
    token: Token[OperationContext | None] = _current_operation_context.set(context)
    try:
        yield
    finally:
        _current_operation_context.reset(token)


async def run_with_deadline[T](awaitable: Awaitable[T], deadline: Deadline) -> T:
    timeout = deadline.expires_at - monotonic()
    if timeout <= 0:
        raise _timeout_error()

    async def operation() -> T:
        return await awaitable

    # Cancellation reaches safe phases immediately.  Once it fires we shield
    # only the final wait: UoW either rolls back before commit or shields and
    # completes a commit that has already begun.
    task = asyncio.create_task(operation())
    try:
        with anyio.fail_after(timeout):
            return await asyncio.shield(task)
    except TimeoutError:
        task.cancel()
        with anyio.CancelScope(shield=True):
            try:
                return await task
            except asyncio.CancelledError as exc:
                raise _timeout_error() from exc
