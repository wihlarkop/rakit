import pytest
from rakit_core.capabilities import CapabilityProvider, CapabilitySet
from rakit_core.compiler import ApplicationBuilder, compile_application
from rakit_core.datasource import DataSourceCapabilities
from rakit_core.definitions import ResourceDefinition, ResourceFieldPolicy, RouteDefinition
from rakit_core.errors import ErrorCode, RakitError
from rakit_core.generated_api import ApiExposure, ResourceApiDefinition
from rakit_core.generated_runtime import GeneratedResourceExecutorContext
from rakit_core.operations import OperationExecutorCapabilities
from rakit_core.query import PageResult


class ReadDataSource:
    capabilities = DataSourceCapabilities(read=True)
    fields = ("id", "email")
    identity_fields = ("id",)

    async def list(self, query):
        return PageResult((), 1, 25, False, False, 0)

    async def count(self, query):
        return 0

    async def detail(self, identity):
        return None


class FakeExecutor:
    capabilities = OperationExecutorCapabilities(participates_in_uow=True)

    async def execute(self, context, request):
        return request


class FakeExecutorProvider:
    def build(self, context: GeneratedResourceExecutorContext) -> FakeExecutor:
        return FakeExecutor()


def _resource(api: ResourceApiDefinition) -> ResourceDefinition:
    return ResourceDefinition(
        resource_id="users",
        path="/users",
        label="Users",
        singular_label="User",
        field_policy=ResourceFieldPolicy(
            list_fields=("id", "email"),
            detail_fields=("id", "email"),
            search_fields=("email",),
            sort_fields=("email",),
        ),
        api=api,
    )


def _generated_routes(compiled):
    return tuple(route for route in compiled.routes if route.route_name.startswith("generated-api:"))


def test_read_only_generated_api_compiles_list_and_detail_rest_routes() -> None:
    builder = ApplicationBuilder()
    builder.add_resource(
        _resource(ResourceApiDefinition(exposure=ApiExposure.READ_ONLY, read_fields=("id", "email"))),
        ReadDataSource(),
    )

    compiled = compile_application(builder)

    assert [
        (route.route_name, route.methods, route.path, route.framework_owned)
        for route in _generated_routes(compiled)
    ] == [
        ("generated-api:users:list", ("GET",), "/api/users", True),
        ("generated-api:users:detail", ("GET",), "/api/users/{identity}", True),
    ]


def test_crud_generated_api_compiles_post_patch_and_delete_rest_routes() -> None:
    class WritableDataSource(ReadDataSource):
        capabilities = DataSourceCapabilities(read=True)
        from rakit_core.fields import FieldDefinition

        field_definitions = (
            FieldDefinition("id", int, writable=False),
            FieldDefinition("email", str, required=True, nullable=False),
        )

    builder = ApplicationBuilder()
    builder.register_capability_provider(
        CapabilityProvider(
            "persistence.example",
            CapabilitySet.of("persistence.write", "transactions.root-uow"),
        )
    )
    builder.add_resource(
        _resource(
            ResourceApiDefinition(
                exposure=ApiExposure.CRUD,
                read_fields=("id", "email"),
                create_fields=("email",),
                update_fields=("email",),
            )
        ),
        WritableDataSource(),
        generated_executor_provider=FakeExecutorProvider(),
    )

    compiled = compile_application(builder)

    assert [(route.route_name, route.methods, route.path) for route in _generated_routes(compiled)] == [
        ("generated-api:users:list", ("GET",), "/api/users"),
        ("generated-api:users:detail", ("GET",), "/api/users/{identity}"),
        ("generated-api:users:create", ("POST",), "/api/users"),
        ("generated-api:users:update", ("PATCH",), "/api/users/{identity}"),
        ("generated-api:users:delete", ("DELETE",), "/api/users/{identity}"),
    ]


def test_none_exposure_compiles_no_generated_rest_routes() -> None:
    builder = ApplicationBuilder()
    builder.add_resource(_resource(ResourceApiDefinition()), ReadDataSource())

    compiled = compile_application(builder)

    assert _generated_routes(compiled) == ()


def test_output_schema_requires_output_serialization_capability() -> None:
    class OutputSchema:
        pass

    builder = ApplicationBuilder()
    builder.add_resource(
        _resource(
            ResourceApiDefinition(
                exposure=ApiExposure.READ_ONLY,
                read_fields=("id", "email"),
                output_schema=OutputSchema,
            )
        ),
        ReadDataSource(),
    )

    with pytest.raises(RakitError) as captured:
        compile_application(builder)

    assert captured.value.details["reason"] == "missing_capabilities"
    assert captured.value.details["missing"] == ["schema.output-serialization"]


def test_api_namespace_is_reserved_for_framework_owned_routes() -> None:
    builder = ApplicationBuilder()
    builder.add_resource(_resource(ResourceApiDefinition()), ReadDataSource())
    builder.add_route(
        RouteDefinition(
            route_name="user.api.route",
            methods=("GET",),
            path="/api/custom",
            owner_id="custom",
        )
    )

    with pytest.raises(RakitError) as captured:
        compile_application(builder)

    assert captured.value.code == ErrorCode.CONFIG_RESERVED_PATH
