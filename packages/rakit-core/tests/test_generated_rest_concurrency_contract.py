from dataclasses import dataclass

from rakit_core.fields import FieldDefinition
from rakit_core.generated_api import (
    ApiExposure,
    CompiledResourceApi,
    ResourceApiDefinition,
)
from rakit_core.generated_input import GeneratedInput
from rakit_core.generated_operations import GeneratedCrudRequest, build_generated_operation_plan
from rakit_core.identity import RecordIdentity
from rakit_core.mutations import OperationAuthorization
from rakit_core.operations import OperationExecutorCapabilities
from rakit_core.permissions import PermissionRequirement


@dataclass
class Executor:
    capabilities = OperationExecutorCapabilities(
        participates_in_uow=True,
        atomic_concurrency=True,
    )

    async def execute(self, context, request):
        return request


def _api() -> CompiledResourceApi:
    definition = ResourceApiDefinition(
        exposure=ApiExposure.CRUD,
        read_fields=("id", "email"),
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
        field_definitions=(
            FieldDefinition("id", int, writable=False),
            FieldDefinition("email", str, required=True, nullable=False),
        ),
    )


def _authorization(operation: str, identity: RecordIdentity) -> OperationAuthorization:
    return OperationAuthorization.for_requirement(
        admin_id="admin",
        resource_id="users",
        operation=operation,
        principal_id="user-1",
        requirement=PermissionRequirement.all_of(f"admin.resources.users.{operation}"),
        target_identity=identity,
    )


def test_partial_update_request_carries_opaque_concurrency_token() -> None:
    identity = RecordIdentity(values={"id": 7})
    payload = GeneratedInput(
        values={"email": "next@example.com"},
        present_fields=frozenset({"email"}),
    )

    request = GeneratedCrudRequest.update_partial(
        identity,
        payload,
        concurrency_token="opaque-etag-token",
    )

    assert request.concurrency_token == "opaque-etag-token"


def test_delete_request_carries_opaque_concurrency_token() -> None:
    identity = RecordIdentity(values={"id": 7})

    request = GeneratedCrudRequest.delete(identity, concurrency_token="opaque-etag-token")

    assert request.concurrency_token == "opaque-etag-token"


def test_delete_operation_plan_can_require_atomic_concurrency() -> None:
    identity = RecordIdentity(values={"id": 7})
    request = GeneratedCrudRequest.delete(identity, concurrency_token="opaque-etag-token")

    plan = build_generated_operation_plan(
        _api(),
        request,
        _authorization("delete", identity),
        Executor(),
        concurrency_required=True,
    )

    assert plan.concurrency_required is True
