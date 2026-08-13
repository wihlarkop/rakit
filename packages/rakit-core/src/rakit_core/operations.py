"""Operation deadlines and cooperative cancellation checkpoints."""

import asyncio
import inspect
import uuid
from collections.abc import Awaitable, Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar, Token
from dataclasses import dataclass
from enum import StrEnum
from time import monotonic
from typing import cast

import anyio

from rakit_core.auth import Principal
from rakit_core.di import ServiceResolver
from rakit_core.errors import ErrorCode, RakitError
from rakit_core.events import EventPublisher
from rakit_core.identity import RecordIdentity
from rakit_core.mutations import OperationAuthorization
from rakit_core.permissions import PermissionRequirement
from rakit_core.transactions import TransactionPolicy


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


class OperationKind(StrEnum):
    ACTION = "action"
    BULK = "bulk"
    ENDPOINT = "endpoint"
    PAGE = "page"
    RELATIONSHIP = "relationship"


type OperationExecutor[TInput, TResult] = Callable[
    ["OperationContext", TInput], TResult | Awaitable[TResult]
]


@dataclass(frozen=True)
class OperationPlan[TInput, TResult]:
    """Immutable, backend-neutral execution seam for Plan 05 operations.

    It deliberately carries policy and a typed executor but does not own a
    concrete unit of work.  A web or adapter operation runner supplies that
    lifecycle later, preserving one operation model without pulling SQLAlchemy
    or HTTP concerns into core.
    """

    operation_id: str
    kind: OperationKind
    input: TInput
    authorization: OperationAuthorization | None
    execute: OperationExecutor[TInput, TResult]
    target_identity: RecordIdentity | None = None
    mutating: bool = False
    transaction_policy: TransactionPolicy = TransactionPolicy.READ_ONLY
    concurrency_required: bool = False
    confirmation_required: bool = False
    idempotency_fingerprint: str | None = None

    def __post_init__(self) -> None:
        if not self.operation_id:
            raise ValueError("operation_id must not be empty")
        if self.mutating and self.transaction_policy is TransactionPolicy.READ_ONLY:
            raise ValueError("Mutating operations cannot use a read-only transaction policy")
        if not self.mutating and self.transaction_policy is TransactionPolicy.AUTO:
            raise ValueError("Read-only operations cannot request an automatic write transaction")


def validate_operation_authorization[TInput, TResult](
    plan: OperationPlan[TInput, TResult], context: "OperationContext"
) -> None:
    """Fail closed before a generic operation executor calls application code."""

    authorization = plan.authorization
    if authorization is None:
        raise RakitError(
            code=ErrorCode.AUTH_FORBIDDEN,
            message="Operation execution requires an explicit authorization capability.",
            status_code=403,
        )
    if (
        context.admin_id != authorization.admin_id
        or context.operation != authorization.operation
        or context.principal_id != authorization.principal_id
        or context.resource_id != authorization.resource_id
        or authorization.target_identity != plan.target_identity
    ):
        raise RakitError(
            code=ErrorCode.AUTH_FORBIDDEN,
            message="Operation authorization does not match the active context.",
            status_code=403,
        )
    expected_requirement = context.permission_requirement
    if expected_requirement is None or authorization.requirement != expected_requirement:
        raise RakitError(
            code=ErrorCode.AUTH_FORBIDDEN,
            message="Operation authorization does not bind the expected permission requirement.",
            status_code=403,
        )


async def execute_operation_plan[TInput, TResult](
    plan: OperationPlan[TInput, TResult], context: "OperationContext"
) -> TResult:
    """Run a prepared operation at the explicit authorization/checkpoint seam."""

    validate_operation_authorization(plan, context)
    context.checkpoint()
    result = plan.execute(context, plan.input)
    if inspect.isawaitable(result):
        return cast("TResult", await result)
    return result


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
    permission_requirement: PermissionRequirement | None = None
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
