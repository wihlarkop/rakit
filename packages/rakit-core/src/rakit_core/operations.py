"""Operation deadlines and cooperative cancellation checkpoints."""

import asyncio
import inspect
import uuid
from collections.abc import Awaitable, Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar, Token
from dataclasses import dataclass, field
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
from rakit_core.transactions import (
    OperationUnitOfWork,
    OperationUnitOfWorkFactory,
    TransactionPolicy,
)


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
    RESOURCE = "resource"


@dataclass(frozen=True)
class OperationExecutorCapabilities:
    """Backend-neutral metadata describing how an operation executor works.

    ``participates_in_uow`` means the executor writes through the Rakit-owned
    root unit of work (it never opens an independent transaction that Rakit
    could not roll back).  ``atomic_concurrency`` means the executor performs
    its persistence write atomically against the verified concurrency state.
    Unknown executors resolve to the all-None default: Rakit guarantees
    nothing it cannot prove.
    """

    participates_in_uow: bool = False
    atomic_concurrency: bool = False

    def __post_init__(self) -> None:
        if self.atomic_concurrency and not self.participates_in_uow:
            raise ValueError("Atomic concurrency requires unit-of-work participation")


def resolve_operation_executor_capabilities(
    executor: object,
) -> OperationExecutorCapabilities:
    """Resolve an executor's declared capabilities with a safe NONE default.

    An executor with a valid explicit ``capabilities`` attribute is trusted;
    anything else -- including objects that merely happen to have an
    ``execute`` method -- resolves to no UoW participation and no atomic
    concurrency guarantee.
    """
    capabilities = getattr(executor, "capabilities", None)
    if isinstance(capabilities, OperationExecutorCapabilities):
        return capabilities
    return OperationExecutorCapabilities()


type OperationExecutor[TInput, TResult] = Callable[
    ["OperationContext", TInput], TResult | Awaitable[TResult]
]


def _default_result_is_success(result: object) -> bool:
    return True


@dataclass(frozen=True)
class OperationPlan[TInput, TResult]:
    """Immutable, backend-neutral execution seam for operations.

    It deliberately carries policy and a typed executor but does not own a
    concrete unit of work.  ``executor_capabilities`` records what the
    executor truthfully supports, and ``result_is_success`` classifies
    whether a returned result represents a successful durable operation
    (the operation lifecycle uses it for AUTO commit decisions).
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
    executor_capabilities: OperationExecutorCapabilities = field(
        default_factory=OperationExecutorCapabilities
    )
    result_is_success: Callable[[TResult], bool] = _default_result_is_success

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
    declared_requirement = PermissionRequirement(
        mode=authorization.permission_mode,
        permissions=authorization.permissions,
    )
    if (
        expected_requirement is None
        or authorization.requirement != declared_requirement
        or authorization.requirement != expected_requirement
    ):
        raise RakitError(
            code=ErrorCode.AUTH_FORBIDDEN,
            message="Operation authorization does not bind the expected permission requirement.",
            status_code=403,
        )


def validate_operation_transaction_contract[TInput, TResult](
    plan: OperationPlan[TInput, TResult],
) -> None:
    """Fail closed when a plan's transaction policy outruns its executor.

    AUTO and MANUAL both mean a Rakit-owned root unit of work exists and the
    executor must participate in it; DISABLED is the explicit escape hatch
    for unmanaged side effects. Strong concurrency additionally requires a
    mutating AUTO operation whose executor advertises atomic UoW concurrency.
    """
    if plan.concurrency_required:
        if not plan.mutating or plan.transaction_policy is not TransactionPolicy.AUTO:
            raise RakitError(
                code=ErrorCode.CONFIG_INVALID,
                message=(
                    f'Strong concurrency for operation "{plan.operation_id}" requires '
                    "a mutating operation with TransactionPolicy.AUTO."
                ),
                status_code=500,
                details={
                    "operation_id": plan.operation_id,
                    "transaction_policy": str(plan.transaction_policy),
                    "reason": "invalid_concurrency_transaction_policy",
                },
            )
        if (
            not plan.executor_capabilities.participates_in_uow
            or not plan.executor_capabilities.atomic_concurrency
        ):
            raise RakitError(
                code=ErrorCode.CONFIG_INVALID,
                message=(
                    f'Strong concurrency for operation "{plan.operation_id}" requires '
                    "an executor with atomic unit-of-work participation."
                ),
                status_code=500,
                details={
                    "operation_id": plan.operation_id,
                    "transaction_policy": str(plan.transaction_policy),
                    "reason": "atomic_concurrency_not_supported",
                },
            )

    if not plan.mutating:
        return

    if (
        plan.transaction_policy in (TransactionPolicy.AUTO, TransactionPolicy.MANUAL)
        and not plan.executor_capabilities.participates_in_uow
    ):
        raise RakitError(
            code=ErrorCode.CONFIG_INVALID,
            message=(
                f"Mutating {plan.transaction_policy.value} operation "
                f'"{plan.operation_id}" requires an executor that participates '
                "in the operation unit of work."
            ),
            status_code=500,
            details={
                "operation_id": plan.operation_id,
                "transaction_policy": str(plan.transaction_policy),
                "reason": "executor_not_uow_managed",
            },
        )


async def run_operation_plan[TInput, TResult](
    plan: OperationPlan[TInput, TResult],
    context: "OperationContext",
    *,
    unit_of_work_factory: OperationUnitOfWorkFactory | None,
) -> TResult:
    """Run one operation through its transaction lifecycle.

    AUTO/MANUAL mutating operations open a root backend-neutral unit of work
    (required), expose it on ``OperationContext.unit_of_work``, execute the
    plan, and let the UoW own the durable outcome: AUTO marks success only
    for results classified successful by ``plan.result_is_success``; MANUAL
    never auto-commits; exceptions and unsuccessful results roll back during
    UoW teardown.  DISABLED and READ_ONLY operations execute without a root
    UoW.  Authorization validation remains exactly ``execute_operation_plan``.
    """
    validate_operation_transaction_contract(plan)
    if plan.mutating and plan.transaction_policy in (
        TransactionPolicy.AUTO,
        TransactionPolicy.MANUAL,
    ):
        if unit_of_work_factory is None:
            raise RakitError(
                code=ErrorCode.CONFIG_INVALID,
                message=(
                    f"Mutating {plan.transaction_policy.value} operation "
                    f'"{plan.operation_id}" requires a registered operation '
                    "unit-of-work provider."
                ),
                status_code=500,
            )
        async with unit_of_work_factory.open(
            policy=plan.transaction_policy,
            event_publisher=context.events,
            operation_context=context,
        ) as unit_of_work:
            object.__setattr__(context, "unit_of_work", unit_of_work)
            try:
                result = await execute_operation_plan(plan, context)
            except BaseException:
                raise
            else:
                if plan.transaction_policy is TransactionPolicy.AUTO and plan.result_is_success(
                    result
                ):
                    await unit_of_work.mark_success()
                return result
            finally:
                object.__setattr__(context, "unit_of_work", None)
    return await execute_operation_plan(plan, context)


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
    session_id: str = ""
    admin_id: str = ""
    resource_id: str = ""
    operation: str = ""
    permissions: tuple[str, ...] = ()
    permission_requirement: PermissionRequirement | None = None
    services: ServiceResolver | None = None
    events: EventPublisher | None = None
    unit_of_work: OperationUnitOfWork | None = None

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
