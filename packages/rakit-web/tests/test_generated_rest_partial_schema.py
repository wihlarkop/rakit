import pytest
from pydantic import BaseModel
from rakit_core.capabilities import CapabilityProvider, CapabilitySet
from rakit_core.compiler import ApplicationBuilder, compile_application
from rakit_core.datasource import DataSourceCapabilities
from rakit_core.definitions import ResourceDefinition, ResourceFieldPolicy
from rakit_core.errors import RakitError
from rakit_core.fields import FieldDefinition
from rakit_core.generated_api import (
    ApiExposure,
    CompiledResourceApi,
    GeneratedCrudOperation,
    ResourceApiDefinition,
)
from rakit_core.generated_input import validate_generated_input
from rakit_core.generated_operations import GeneratedCrudRequest
from rakit_core.generated_runtime import GeneratedResourceExecutorContext
from rakit_core.identity import RecordIdentity
from rakit_core.operations import OperationExecutorCapabilities
from rakit_core.query import PageResult
from rakit_schema_pydantic import PydanticSchemaAdapter


class UpdateUser(BaseModel):
    email: str | None = None
    nickname: str | None = None


FIELDS = (
    FieldDefinition("id", int, writable=False),
    FieldDefinition("email", str, nullable=True),
    FieldDefinition("nickname", str, nullable=True),
)


def _compiled_api() -> CompiledResourceApi:
    definition = ResourceApiDefinition(
        exposure=ApiExposure.CRUD,
        read_fields=("id", "email", "nickname"),
        create_fields=("email", "nickname"),
        update_fields=("email", "nickname"),
        update_schema=UpdateUser,
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


def test_pydantic_partial_schema_preserves_omitted_fields() -> None:
    parsed = validate_generated_input(
        _compiled_api(),
        operation=GeneratedCrudOperation.UPDATE_PARTIAL,
        submitted={"nickname": "neo"},
        field_definitions=FIELDS,
        schema_adapter=PydanticSchemaAdapter(),
    )

    assert dict(parsed.values) == {"nickname": "neo"}
    assert parsed.present_fields == frozenset({"nickname"})
    request = GeneratedCrudRequest.update_partial(
        identity=RecordIdentity(values={"id": 1}),
        input=parsed,
    )
    assert request.input is not None
    assert dict(request.input.values) == {"nickname": "neo"}


class DataSource:
    capabilities = DataSourceCapabilities(read=True)
    fields = ("id", "email", "nickname")
    identity_fields = ("id",)
    field_definitions = FIELDS

    async def list(self, query):
        return PageResult((), 1, 25, False, False, 0)

    async def count(self, query):
        return 0

    async def detail(self, identity):
        return None


class Executor:
    capabilities = OperationExecutorCapabilities(participates_in_uow=True)

    async def execute(self, context, request):
        return request


class Provider:
    def build(self, context: GeneratedResourceExecutorContext) -> Executor:
        return Executor()


def test_update_schema_requires_partial_update_capability() -> None:
    builder = ApplicationBuilder()
    builder.register_capability_provider(
        CapabilityProvider(
            "persistence.example",
            CapabilitySet.of("persistence.write", "transactions.root-uow"),
        )
    )
    builder.register_capability_provider(
        CapabilityProvider(
            "schema.incomplete",
            CapabilitySet.of("schema.input-validation", "schema.output-serialization"),
        )
    )
    builder.add_resource(
        ResourceDefinition(
            resource_id="users",
            path="/users",
            label="Users",
            singular_label="User",
            field_policy=ResourceFieldPolicy(
                list_fields=("id", "email", "nickname"),
                detail_fields=("id", "email", "nickname"),
            ),
            api=_compiled_api().definition,
        ),
        DataSource(),
        generated_executor_provider=Provider(),
    )

    with pytest.raises(RakitError) as captured:
        compile_application(builder)

    assert captured.value.details["reason"] == "missing_capabilities"
    assert captured.value.details["missing"] == ["schema.partial-update"]
