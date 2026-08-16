"""Backend-neutral custom page execution primitives.

Pages are permission-bound application operations. Core owns their typed
results and operation plan; web adapters own HTTP parsing and template
rendering. Mutating pages use POST/Redirect/Get: a successful mutating page
must return :class:`PageRedirect`, which makes idempotent replay safe without
persisting arbitrary rendered payloads.
"""

import inspect
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from typing import Any, cast

from pydantic import BaseModel

from rakit_core.actions import ActionRedirect
from rakit_core.auth import Principal
from rakit_core.definitions import PageDefinition
from rakit_core.mutations import OperationAuthorization
from rakit_core.operations import (
    OperationContext,
    OperationExecutor,
    OperationExecutorCapabilities,
    OperationKind,
    OperationPlan,
    resolve_operation_executor_capabilities,
    validate_operation_transaction_contract,
)


@dataclass(frozen=True)
class PageResult[TPagePayload]:
    """Semantic rendered-page result; payload is passed to the page template."""

    payload: TPagePayload | None = None
    message: str | None = None
    status_code: int = 200

    def __post_init__(self) -> None:
        if not 200 <= self.status_code < 300:
            raise ValueError("Rendered page status_code must be a 2xx status")


@dataclass(frozen=True)
class PageRedirect:
    """Safe internal redirect used for POST/Redirect/Get and optional GET redirects."""

    location: str
    message: str | None = None

    def __post_init__(self) -> None:
        # Reuse the already sealed internal-redirect trust-boundary validation.
        ActionRedirect(location=self.location)


@dataclass(frozen=True)
class PageRejected:
    """Expected page/business rejection; it never marks an AUTO UoW successful."""

    errors: Mapping[str, str]
    message: str | None = None
    status_code: int = 409

    def __post_init__(self) -> None:
        if not self.errors and self.message is None:
            raise ValueError("A rejected page result requires errors or a message")
        if not 400 <= self.status_code < 500:
            raise ValueError("Rejected page status_code must be a 4xx status")


type PageExecutionResult[TPagePayload] = PageResult[TPagePayload] | PageRedirect | PageRejected


@dataclass(frozen=True)
class PageContext:
    """Prepared page input and trusted authorization passed to application code."""

    definition: PageDefinition
    values: BaseModel | None = None
    authorization: OperationAuthorization | None = None
    principal: Principal | None = None


class DomainPageHandler:
    """Wrap arbitrary sync/async application code for read-only or unmanaged pages."""

    capabilities: OperationExecutorCapabilities = OperationExecutorCapabilities()

    def __init__(
        self,
        handler: Callable[
            [PageContext],
            PageExecutionResult[Any] | Awaitable[PageExecutionResult[Any]],
        ],
    ) -> None:
        if not callable(handler):
            raise TypeError("Domain page handler must be callable")
        self._handler = handler

    async def __call__(self, context: PageContext) -> PageExecutionResult[Any]:
        result = self._handler(context)
        if inspect.isawaitable(result):
            result = await result
        return _validate_page_result(result)


class PreparedPageMutationHandler:
    """Mutating page handler that participates in Rakit's root operation UoW."""

    capabilities: OperationExecutorCapabilities = OperationExecutorCapabilities(
        participates_in_uow=True
    )

    def __init__(
        self,
        prepare: Callable[[PageContext], object | Awaitable[object]],
        commit: Callable[
            [object, PageContext],
            PageExecutionResult[Any] | Awaitable[PageExecutionResult[Any]],
        ],
    ) -> None:
        if not callable(prepare) or not callable(commit):
            raise TypeError("Page mutation prepare and commit must be callable")
        self._prepare = prepare
        self._commit = commit

    async def __call__(self, context: PageContext) -> PageExecutionResult[Any]:
        prepared = self._prepare(context)
        if inspect.isawaitable(prepared):
            prepared = await prepared
        result = self._commit(prepared, context)
        if inspect.isawaitable(result):
            result = await result
        return _validate_page_result(result)


def _validate_page_result(result: object) -> PageExecutionResult[Any]:
    if isinstance(result, PageResult | PageRedirect | PageRejected):
        return result
    raise TypeError("Page handlers must return PageResult, PageRedirect, or PageRejected")


def _page_result_is_success(result: object, *, mutating: bool) -> bool:
    if mutating:
        # Mutating pages are deliberately PRG-only. A rendered or rejected
        # result rolls the root UoW back before the web layer translates it.
        return isinstance(result, PageRedirect)
    return isinstance(result, PageResult | PageRedirect)


def build_page_operation_plan(
    context: PageContext,
    *,
    idempotency_fingerprint: str | None = None,
) -> OperationPlan[PageContext, PageExecutionResult[Any]]:
    """Map a prepared page request to the canonical operation seam."""

    definition = context.definition
    handler = definition.handler
    if handler is None or not callable(handler):
        raise ValueError(f"Page {definition.page_id!r} requires a callable handler")
    authorization = context.authorization
    if authorization is None:
        raise ValueError(f"Page {definition.page_id!r} has no authorization capability")
    if authorization.target_identity is not None:
        raise ValueError("Page authorization cannot carry a record target")

    capabilities = resolve_operation_executor_capabilities(handler)

    async def execute(
        _operation_context: OperationContext, page_context: PageContext
    ) -> PageExecutionResult[Any]:
        result = handler(page_context)
        if inspect.isawaitable(result):
            result = await result
        return _validate_page_result(result)

    plan_execute: OperationExecutor[PageContext, PageExecutionResult[Any]] = execute
    plan = cast(
        OperationPlan[PageContext, PageExecutionResult[Any]],
        OperationPlan(
            operation_id=str(definition.page_id),
            kind=OperationKind.PAGE,
            input=context,
            authorization=authorization,
            mutating=definition.mutating,
            transaction_policy=definition.transaction_policy,
            idempotency_fingerprint=idempotency_fingerprint,
            executor_capabilities=capabilities,
            result_is_success=lambda result: _page_result_is_success(
                result, mutating=definition.mutating
            ),
            execute=plan_execute,
        ),
    )
    validate_operation_transaction_contract(plan)
    return plan


__all__ = [
    "DomainPageHandler",
    "PageContext",
    "PageExecutionResult",
    "PageRedirect",
    "PageRejected",
    "PageResult",
    "PreparedPageMutationHandler",
    "build_page_operation_plan",
]
