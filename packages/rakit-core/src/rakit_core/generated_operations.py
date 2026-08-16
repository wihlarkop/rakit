from dataclasses import dataclass
from typing import Protocol

from .generated_api import CompiledResourceApi, GeneratedCrudOperation
from .generated_input import GeneratedInput
from .identity import RecordIdentity
from .mutations import OperationAuthorization
from .operations import (
    OperationContext,
    OperationExecutorCapabilities,
    OperationKind,
    OperationPlan,
    resolve_operation_executor_capabilities,
)
from .query import ResourceQuery
from .transactions import TransactionPolicy


@dataclass(frozen=True, slots=True)
class GeneratedCrudRequest:
    operation: GeneratedCrudOperation
    query: ResourceQuery | None = None
    identity: RecordIdentity | None = None
    input: GeneratedInput | None = None
    concurrency_token: str | None = None

    def __post_init__(self) -> None:
        if self.operation is GeneratedCrudOperation.LIST:
            if (
                self.query is None
                or self.identity is not None
                or self.input is not None
                or self.concurrency_token is not None
            ):
                raise ValueError("A list request requires only a ResourceQuery")
            return
        if self.operation is GeneratedCrudOperation.DETAIL:
            if (
                self.identity is None
                or self.query is not None
                or self.input is not None
                or self.concurrency_token is not None
            ):
                raise ValueError("A detail request requires only an identity")
            return
        if self.operation is GeneratedCrudOperation.CREATE:
            if (
                self.input is None
                or self.query is not None
                or self.identity is not None
                or self.concurrency_token is not None
            ):
                raise ValueError("A create request requires only generated input")
            return
        if self.operation is GeneratedCrudOperation.UPDATE_PARTIAL:
            if self.identity is None or self.input is None or self.query is not None:
                raise ValueError("A partial update request requires identity and generated input")
            return
        if self.operation is GeneratedCrudOperation.DELETE:
            if self.identity is None or self.query is not None or self.input is not None:
                raise ValueError("A delete request requires only an identity")
            return
        raise ValueError("Unsupported generated CRUD operation")

    @classmethod
    def list(cls, query: ResourceQuery) -> "GeneratedCrudRequest":
        return cls(operation=GeneratedCrudOperation.LIST, query=query)

    @classmethod
    def detail(cls, identity: RecordIdentity) -> "GeneratedCrudRequest":
        return cls(operation=GeneratedCrudOperation.DETAIL, identity=identity)

    @classmethod
    def create(cls, input: GeneratedInput) -> "GeneratedCrudRequest":
        return cls(operation=GeneratedCrudOperation.CREATE, input=input)

    @classmethod
    def update_partial(
        cls,
        identity: RecordIdentity,
        input: GeneratedInput,
        *,
        concurrency_token: str | None = None,
    ) -> "GeneratedCrudRequest":
        return cls(
            operation=GeneratedCrudOperation.UPDATE_PARTIAL,
            identity=identity,
            input=input,
            concurrency_token=concurrency_token,
        )

    @classmethod
    def delete(
        cls,
        identity: RecordIdentity,
        *,
        concurrency_token: str | None = None,
    ) -> "GeneratedCrudRequest":
        return cls(
            operation=GeneratedCrudOperation.DELETE,
            identity=identity,
            concurrency_token=concurrency_token,
        )


class GeneratedResourceExecutor(Protocol):
    capabilities: OperationExecutorCapabilities

    async def execute(self, context: OperationContext, request: GeneratedCrudRequest) -> object: ...


_AUTH_OPERATION = {
    GeneratedCrudOperation.LIST: "list",
    GeneratedCrudOperation.DETAIL: "detail",
    GeneratedCrudOperation.CREATE: "create",
    GeneratedCrudOperation.UPDATE_PARTIAL: "update",
    GeneratedCrudOperation.DELETE: "delete",
}


def build_generated_operation_plan(
    api: CompiledResourceApi,
    request: GeneratedCrudRequest,
    authorization: OperationAuthorization,
    executor: GeneratedResourceExecutor,
    *,
    concurrency_required: bool = False,
    idempotency_fingerprint: str | None = None,
) -> OperationPlan[GeneratedCrudRequest, object]:
    if request.operation not in api.operations:
        raise ValueError(
            "Generated operation "
            f"{request.operation.value!r} is not exposed by resource "
            f"{api.resource_id!r}"
        )

    expected_operation = _AUTH_OPERATION[request.operation]
    if (
        authorization.resource_id != api.resource_id
        or authorization.operation != expected_operation
        or authorization.target_identity != request.identity
    ):
        raise ValueError("Generated operation authorization does not match the request")

    mutating = request.operation in {
        GeneratedCrudOperation.CREATE,
        GeneratedCrudOperation.UPDATE_PARTIAL,
        GeneratedCrudOperation.DELETE,
    }
    if concurrency_required and request.operation not in {
        GeneratedCrudOperation.UPDATE_PARTIAL,
        GeneratedCrudOperation.DELETE,
    }:
        raise ValueError("Generated concurrency may only be required for update or delete")

    return OperationPlan(
        operation_id=f"generated-resource:{api.resource_id}:{request.operation.value}",
        kind=OperationKind.RESOURCE,
        input=request,
        authorization=authorization,
        execute=executor.execute,
        target_identity=request.identity,
        mutating=mutating,
        transaction_policy=TransactionPolicy.AUTO if mutating else TransactionPolicy.READ_ONLY,
        concurrency_required=concurrency_required,
        idempotency_fingerprint=idempotency_fingerprint,
        executor_capabilities=resolve_operation_executor_capabilities(executor),
    )


__all__ = [
    "GeneratedCrudRequest",
    "GeneratedResourceExecutor",
    "build_generated_operation_plan",
]
