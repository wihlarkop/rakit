import pytest
from rakit_core.capabilities import CapabilityProvider, CapabilitySet
from rakit_core.compiler import ApplicationBuilder, compile_application
from rakit_core.datasource import DataSourceCapabilities
from rakit_core.definitions import ResourceDefinition, ResourceFieldPolicy
from rakit_core.errors import RakitError
from rakit_core.fields import FieldDefinition
from rakit_core.generated_api import ApiExposure, ResourceApiDefinition
from rakit_core.generated_runtime import GeneratedResourceExecutorContext
from rakit_core.operations import OperationExecutorCapabilities
from rakit_core.query import PageResult


class WritableDataSource:
    capabilities = DataSourceCapabilities(read=True)
    fields = ("id", "email")
    identity_fields = ("id",)
    field_definitions = (
        FieldDefinition("id", int, writable=False),
        FieldDefinition("email", str, required=True, nullable=False),
    )

    async def list(self, query):
        return PageResult((), 1, 25, False, False, 0)

    async def count(self, query):
        return 0

    async def detail(self, identity):
        return None


class Executor:
    capabilities = OperationExecutorCapabilities(
        participates_in_uow=True,
        atomic_concurrency=True,
    )

    async def execute(self, context, request):
        return request


class Provider:
    def build(self, context: GeneratedResourceExecutorContext) -> Executor:
        return Executor()


def _resource() -> ResourceDefinition:
    return ResourceDefinition(
        resource_id="users",
        path="/users",
        label="Users",
        singular_label="User",
        field_policy=ResourceFieldPolicy(
            list_fields=("id", "email"),
            detail_fields=("id", "email"),
        ),
        api=ResourceApiDefinition(
            exposure=ApiExposure.CRUD,
            read_fields=("id", "email"),
            create_fields=("email",),
            update_fields=("email",),
        ),
    )


def _builder() -> ApplicationBuilder:
    builder = ApplicationBuilder()
    builder.register_capability_provider(
        CapabilityProvider(
            "persistence.example",
            CapabilitySet.of("persistence.write", "transactions.root-uow"),
        )
    )
    return builder


def _generated_routes(compiled):
    return tuple(
        route for route in compiled.routes if route.route_name.startswith("generated-api:")
    )


def test_crud_with_generated_executor_projects_mutation_routes() -> None:
    builder = _builder()
    provider = Provider()
    builder.add_resource(
        _resource(),
        WritableDataSource(),
        generated_executor_provider=provider,
    )

    compiled = compile_application(builder)

    assert [(route.route_name, route.methods, route.path) for route in _generated_routes(compiled)] == [
        ("generated-api:users:list", ("GET", "HEAD"), "/api/users"),
        ("generated-api:users:detail", ("GET", "HEAD"), "/api/users/{identity}"),
        ("generated-api:users:create", ("POST",), "/api/users"),
        ("generated-api:users:update", ("PATCH",), "/api/users/{identity}"),
        ("generated-api:users:delete", ("DELETE",), "/api/users/{identity}"),
    ]
    assert compiled.generated_resource_executor_providers == (("users", provider),)


def test_crud_without_generated_executor_fails_closed() -> None:
    builder = _builder()
    builder.add_resource(_resource(), WritableDataSource())

    with pytest.raises(RakitError) as captured:
        compile_application(builder)

    assert captured.value.details == {
        "resource_id": "users",
        "reason": "generated_api_executor_not_supported",
    }
