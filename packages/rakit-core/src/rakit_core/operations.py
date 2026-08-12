"""Operation deadlines and cooperative cancellation checkpoints."""

import asyncio
from collections.abc import Awaitable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar, Token
from dataclasses import dataclass
from time import monotonic

from rakit_core.errors import ErrorCode, RakitError


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
    deadline: Deadline
    cancellation: CancellationContext

    def checkpoint(self) -> None:
        self.cancellation.check(self.deadline)


_current_operation_context: ContextVar[OperationContext | None] = ContextVar(
    "rakit_current_operation_context", default=None
)


def current_operation_context() -> OperationContext | None:
    """The request operation context, available to adapters in this task only."""
    return _current_operation_context.get()


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
    try:
        async with asyncio.timeout(timeout):
            return await awaitable
    except TimeoutError as exc:
        raise _timeout_error() from exc
