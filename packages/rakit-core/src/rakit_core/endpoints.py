"""Backend-neutral typed custom endpoint primitives.

Endpoint declarations and execution remain semantic: core knows about
methods, input sources, access policy, transaction ownership and structured
results, while a web adapter owns HTTP parsing and concrete responses.
"""

import inspect
from collections.abc import AsyncIterable, Awaitable, Callable, Iterable
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, cast

from .auth import Principal
from .mutations import OperationAuthorization
from .operations import (
    OperationContext,
    OperationExecutor,
    OperationExecutorCapabilities,
    OperationKind,
    OperationPlan,
    resolve_operation_executor_capabilities,
    validate_operation_transaction_contract,
)
from .transactions import TransactionPolicy


class EndpointInputSource(StrEnum):
    QUERY = "query"
    JSON = "json"
    FORM = "form"


class EndpointMethod(StrEnum):
    GET = "GET"
    POST = "POST"


class EndpointAccessPolicy(StrEnum):
    """Endpoint exposure is private unless a declaration opts in explicitly."""

    PRIVATE = "private"
    PUBLIC = "public"


class EndpointResponseKind(StrEnum):
    """Semantic result transport; web adapters map these to concrete responses."""

    JSON = "json"
    FILE = "file"
    STREAM = "stream"
    ADVANCED = "advanced"


@dataclass(frozen=True)
class EndpointResult[TEndpointPayload]:
    """Validated JSON endpoint result."""

    payload: TEndpointPayload
    status_code: int = 200
    kind: EndpointResponseKind = EndpointResponseKind.JSON

    def __post_init__(self) -> None:
        if self.kind is not EndpointResponseKind.JSON:
            raise ValueError("EndpointResult is the JSON result type")
        if not 200 <= self.status_code < 300:
            raise ValueError("EndpointResult.status_code must be a 2xx status")


@dataclass(frozen=True)
class EndpointFileResult:
    """Finite file response whose bytes already exist before HTTP streaming starts."""

    content: bytes
    filename: str
    content_type: str = "application/octet-stream"
    status_code: int = 200
    kind: EndpointResponseKind = EndpointResponseKind.FILE

    def __post_init__(self) -> None:
        if not self.filename or "/" in self.filename or "\\" in self.filename:
            raise ValueError("Endpoint file name must be a safe basename")
        if not self.content_type.strip():
            raise ValueError("Endpoint file content_type must not be empty")
        if not 200 <= self.status_code < 300:
            raise ValueError("Endpoint file status_code must be a 2xx status")


@dataclass(frozen=True)
class EndpointStreamResult:
    """Explicit stream response.

    The web adapter may iterate this only after endpoint operation execution has
    returned. Streaming endpoints are restricted to read-only GET operations,
    so no Rakit-owned write transaction can remain open while bytes are sent.
    """

    stream: AsyncIterable[bytes] | Iterable[bytes]
    content_type: str = "application/octet-stream"
    status_code: int = 200
    kind: EndpointResponseKind = EndpointResponseKind.STREAM

    def __post_init__(self) -> None:
        if not self.content_type.strip():
            raise ValueError("Endpoint stream content_type must not be empty")
        if not 200 <= self.status_code < 300:
            raise ValueError("Endpoint stream status_code must be a 2xx status")


type EndpointExecutionResult[TEndpointPayload] = (
    EndpointResult[TEndpointPayload] | EndpointFileResult | EndpointStreamResult
)


@dataclass(frozen=True)
class AdminEndpoint:
    """Public endpoint declaration used by ``Admin.register_endpoint``.

    GET defaults to QUERY + READ_ONLY. POST defaults to JSON + AUTO. Public
    public mutation endpoints are intentionally unsupported because anonymous
    idempotency ownership needs a separately designed client identity model.
    """

    endpoint_id: str
    path: str
    method: EndpointMethod
    handler: Callable[..., object]
    input_schema: type[object] | None = None
    input_source: EndpointInputSource | None = None
    output_schema: type[object] | None = None
    access_policy: EndpointAccessPolicy = EndpointAccessPolicy.PRIVATE
    response_kind: EndpointResponseKind = EndpointResponseKind.JSON
    allow_response_escape_hatch: bool = False
    transaction_policy: TransactionPolicy | None = None

    def __post_init__(self) -> None:
        if not callable(self.handler):
            raise TypeError("AdminEndpoint.handler must be callable")
        if self.input_schema is None and self.input_source is not None:
            raise ValueError("Endpoint input source requires an input schema")
        if self.input_schema is not None and self.input_source is None:
            object.__setattr__(
                self,
                "input_source",
                EndpointInputSource.QUERY
                if self.method is EndpointMethod.GET
                else EndpointInputSource.JSON,
            )
        if self.transaction_policy is None:
            object.__setattr__(
                self,
                "transaction_policy",
                TransactionPolicy.READ_ONLY
                if self.method is EndpointMethod.GET
                else TransactionPolicy.AUTO,
            )
        if (
            self.method is EndpointMethod.GET
            and self.transaction_policy is not TransactionPolicy.READ_ONLY
        ):
            raise ValueError("GET endpoints must use TransactionPolicy.READ_ONLY")
        if (
            self.method is EndpointMethod.POST
            and self.transaction_policy is TransactionPolicy.READ_ONLY
        ):
            raise ValueError("POST endpoints cannot use TransactionPolicy.READ_ONLY")
        if self.access_policy is EndpointAccessPolicy.PUBLIC and self.method is EndpointMethod.POST:
            raise ValueError("Public POST endpoints are not supported")
        if (
            self.response_kind is not EndpointResponseKind.JSON
            and not self.allow_response_escape_hatch
        ):
            raise ValueError("Non-JSON endpoint responses require explicit escape hatch opt-in")
        if self.response_kind is not EndpointResponseKind.JSON and self.output_schema is not None:
            raise ValueError("Non-JSON endpoint responses cannot declare a JSON output schema")
        if (
            self.method is EndpointMethod.POST
            and self.response_kind is not EndpointResponseKind.JSON
        ):
            raise ValueError("POST endpoints must return JSON")


@dataclass(frozen=True)
class EndpointContext:
    """Prepared endpoint input and trusted request access passed to application code."""

    endpoint_id: str
    values: object | None = None
    authorization: OperationAuthorization | None = None
    principal: Principal | None = None


class DomainEndpointHandler:
    """Wrap arbitrary sync/async read-only endpoint application code."""

    capabilities: OperationExecutorCapabilities = OperationExecutorCapabilities()

    def __init__(
        self,
        handler: Callable[
            [EndpointContext],
            EndpointExecutionResult[Any] | Awaitable[EndpointExecutionResult[Any]],
        ],
    ) -> None:
        if not callable(handler):
            raise TypeError("Domain endpoint handler must be callable")
        self._handler = handler

    async def __call__(self, context: EndpointContext) -> EndpointExecutionResult[Any]:
        result = self._handler(context)
        if inspect.isawaitable(result):
            result = await result
        return _validate_endpoint_result(result)


class EndpointMutationHandler:
    """POST endpoint handler that participates in Rakit's root operation UoW."""

    capabilities: OperationExecutorCapabilities = OperationExecutorCapabilities(
        participates_in_uow=True
    )

    def __init__(
        self,
        handler: Callable[
            [EndpointContext],
            EndpointExecutionResult[Any] | Awaitable[EndpointExecutionResult[Any]],
        ],
    ) -> None:
        if not callable(handler):
            raise TypeError("Endpoint mutation handler must be callable")
        self._handler = handler

    async def __call__(self, context: EndpointContext) -> EndpointExecutionResult[Any]:
        result = self._handler(context)
        if inspect.isawaitable(result):
            result = await result
        return _validate_endpoint_result(result)


def _validate_endpoint_result(result: object) -> EndpointExecutionResult[Any]:
    if isinstance(result, EndpointResult | EndpointFileResult | EndpointStreamResult):
        return result
    raise TypeError(
        "Endpoint handlers must return EndpointResult, EndpointFileResult, or EndpointStreamResult"
    )


def build_endpoint_operation_plan(
    context: EndpointContext,
    *,
    handler: Callable[..., object],
    mutating: bool,
    transaction_policy: TransactionPolicy,
    idempotency_fingerprint: str | None = None,
) -> OperationPlan[EndpointContext, EndpointExecutionResult[Any]]:
    """Map a prepared endpoint request to the canonical operation seam."""

    authorization = context.authorization
    if authorization is None:
        raise ValueError(f"Endpoint {context.endpoint_id!r} has no access capability")
    capabilities = resolve_operation_executor_capabilities(handler)

    async def execute(
        _operation_context: OperationContext, endpoint_context: EndpointContext
    ) -> EndpointExecutionResult[Any]:
        result = handler(endpoint_context)
        if inspect.isawaitable(result):
            result = await result
        return _validate_endpoint_result(result)

    plan_execute: OperationExecutor[EndpointContext, EndpointExecutionResult[Any]] = execute
    plan = cast(
        OperationPlan[EndpointContext, EndpointExecutionResult[Any]],
        OperationPlan(
            operation_id=context.endpoint_id,
            kind=OperationKind.ENDPOINT,
            input=context,
            authorization=authorization,
            mutating=mutating,
            transaction_policy=transaction_policy,
            idempotency_fingerprint=idempotency_fingerprint,
            executor_capabilities=capabilities,
            result_is_success=lambda result: 200 <= result.status_code < 300,
            execute=plan_execute,
        ),
    )
    validate_operation_transaction_contract(plan)
    return plan


__all__ = [
    "AdminEndpoint",
    "DomainEndpointHandler",
    "EndpointAccessPolicy",
    "EndpointContext",
    "EndpointExecutionResult",
    "EndpointFileResult",
    "EndpointInputSource",
    "EndpointMethod",
    "EndpointMutationHandler",
    "EndpointResponseKind",
    "EndpointResult",
    "EndpointStreamResult",
    "build_endpoint_operation_plan",
]
