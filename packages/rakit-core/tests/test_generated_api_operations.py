from dataclasses import dataclass

import pytest
from rakit_core.fields import FieldDefinition
from rakit_core.generated_api import (
    ApiExposure,
    CompiledResourceApi,
    GeneratedCrudOperation,
    ResourceApiDefinition,
)
from rakit_core.generated_input import GeneratedInput
from rakit_core.generated_operations import GeneratedCrudRequest, build_generated_operation_plan
from rakit_core.identity import RecordIdentity
from rakit_core.mutations import OperationAuthorization
from rakit_core.operations import OperationExecutorCapabilities, OperationKind
from rakit_core.permissions import PermissionRequirement
from rakit_core.query import ResourceQuery
from rakit_core.transactions import TransactionPolicy

FIELDS = (FieldDefinition("email", str, required=True),)


def _api() -> CompiledResourceApi:
    definition = ResourceApiDefinition(
        exposure=ApiExposure.CRUD,
        read_fields=("email",),
        create_fields=("email",),
        update_fields=("email",),
    )
    return CompiledResourceApi(
        resource_id="users",
        definition=definition,
        operations=definition.operations,
        read_fields=definition.read_fields,
        create_fields=definition.create_fields,
        update_fields=definition.update_fields,
        identity_fields=("id",),
        filters=(),
        field_definitions=FIELDS,
    )


def _authorization(
    operation: str, identity: RecordIdentity | None = None
) -> OperationAuthorization:
    requirement = PermissionRequirement.all_of(f"resources.users.{operation}")
    return OperationAuthorization.for_requirement(
        admin_id="admin",
        resource_id="users",
        operation=operation,
        principal_id="principal",
        requirement=requirement,
        target_identity=identity,
    )


@dataclass
class FakeExecutor:
    capabilities = OperationExecutorCapabilities(
        participates_in_uow=True,
        atomic_concurrency=True,
    )

    async def execute(self, context, request):
        return request


def test_list_and_detail_build_read_only_resource_plans() -> None:
    executor = FakeExecutor()
    list_request = GeneratedCrudRequest.list(ResourceQuery())
    list_plan = build_generated_operation_plan(
        _api(), list_request, _authorization("list"), executor
    )

    assert list_plan.operation_id == "generated-resource:users:list"
    assert list_plan.kind is OperationKind.RESOURCE
    assert list_plan.mutating is False
    assert list_plan.transaction_policy is TransactionPolicy.READ_ONLY
    assert list_plan.target_identity is None

    identity = RecordIdentity(values={"id": 7})
    detail_request = GeneratedCrudRequest.detail(identity)
    detail_plan = build_generated_operation_plan(
        _api(), detail_request, _authorization("detail", identity), executor
    )
    assert detail_plan.target_identity == identity
    assert detail_plan.transaction_policy is TransactionPolicy.READ_ONLY


def test_create_partial_update_and_delete_use_auto_transaction() -> None:
    executor = FakeExecutor()
    created = GeneratedInput(values={"email": "a@example.com"}, present_fields={"email"})
    create_plan = build_generated_operation_plan(
        _api(),
        GeneratedCrudRequest.create(created),
        _authorization("create"),
        executor,
        idempotency_fingerprint="create-fingerprint",
    )
    assert create_plan.mutating is True
    assert create_plan.transaction_policy is TransactionPolicy.AUTO
    assert create_plan.idempotency_fingerprint == "create-fingerprint"

    identity = RecordIdentity(values={"id": 7})
    update_plan = build_generated_operation_plan(
        _api(),
        GeneratedCrudRequest.update_partial(identity, created),
        _authorization("update", identity),
        executor,
        concurrency_required=True,
        idempotency_fingerprint="update-fingerprint",
    )
    assert update_plan.target_identity == identity
    assert update_plan.concurrency_required is True
    assert update_plan.transaction_policy is TransactionPolicy.AUTO

    delete_plan = build_generated_operation_plan(
        _api(),
        GeneratedCrudRequest.delete(identity),
        _authorization("delete", identity),
        executor,
        idempotency_fingerprint="delete-fingerprint",
    )
    assert delete_plan.target_identity == identity
    assert delete_plan.mutating is True
    assert delete_plan.transaction_policy is TransactionPolicy.AUTO


def test_builder_rejects_operation_not_exposed_by_resource() -> None:
    read_definition = ResourceApiDefinition(exposure=ApiExposure.READ_ONLY)
    api = CompiledResourceApi(
        resource_id="users",
        definition=read_definition,
        operations=read_definition.operations,
        read_fields=("email",),
        create_fields=(),
        update_fields=(),
        identity_fields=("id",),
        filters=(),
    )

    with pytest.raises(ValueError, match="not exposed"):
        build_generated_operation_plan(
            api,
            GeneratedCrudRequest.create(
                GeneratedInput(values={"email": "x"}, present_fields={"email"})
            ),
            _authorization("create"),
            FakeExecutor(),
        )


def test_request_shape_is_operation_specific() -> None:
    identity = RecordIdentity(values={"id": 1})
    with pytest.raises(ValueError, match="list request"):
        GeneratedCrudRequest(
            operation=GeneratedCrudOperation.LIST,
            identity=identity,
        )
