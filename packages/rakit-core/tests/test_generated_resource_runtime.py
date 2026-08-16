import pytest
from rakit_core.capabilities import CapabilityProvider, CapabilitySet
from rakit_core.compiler import ApplicationBuilder, compile_application
from rakit_core.datasource import DataSourceCapabilities
from rakit_core.definitions import ResourceDefinition, ResourceFieldPolicy
from rakit_core.errors import RakitError
from rakit_core.fields import FieldDefinition
from rakit_core.generated_api import ApiExposure, ResourceApiDefinition
from rakit_core.generated_runtime import (
    GeneratedResourceExecutorContext,
    ResourceAdapterRuntime,
    normalize_resource_adapter_runtime,
)
from rakit_core.operations import OperationExecutorCapabilities
from rakit_core.query import PageResult


class FakeDataSource:
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


class FakeExecutor:
    capabilities = OperationExecutorCapabilities(participates_in_uow=True)

    async def execute(self, context, request):
        return request


class FakeProvider:
    def build(self, context: GeneratedResourceExecutorContext) -> FakeExecutor:
        assert context.resource_id == "users"
        return FakeExecutor()


def _resource(exposure: ApiExposure) -> ResourceDefinition:
    api = (
        ResourceApiDefinition(
            exposure=ApiExposure.CRUD,
            read_fields=("id", "email"),
            create_fields=("email",),
            update_fields=("email",),
        )
        if exposure is ApiExposure.CRUD
        else ResourceApiDefinition(
            exposure=exposure,
            read_fields=("id", "email") if exposure is not ApiExposure.NONE else (),
        )
    )
    return ResourceDefinition(
        resource_id="users",
        path="/users",
        label="Users",
        singular_label="User",
        field_policy=ResourceFieldPolicy(
            list_fields=("id", "email"),
            detail_fields=("id", "email"),
        ),
        api=api,
    )


def _register_write_capabilities(builder: ApplicationBuilder) -> None:
    builder.register_capability_provider(
        CapabilityProvider(
            "persistence.example",
            CapabilitySet.of("persistence.write", "transactions.root-uow"),
        )
    )


def test_plain_datasource_normalizes_to_runtime_without_generated_executor() -> None:
    datasource = FakeDataSource()

    runtime = normalize_resource_adapter_runtime(datasource)

    assert runtime.data_source is datasource
    assert runtime.generated_executor_provider is None


def test_resource_adapter_runtime_retains_generated_executor_provider() -> None:
    datasource = FakeDataSource()
    provider = FakeProvider()

    runtime = normalize_resource_adapter_runtime(
        ResourceAdapterRuntime(
            data_source=datasource,
            generated_executor_provider=provider,
        )
    )

    assert runtime.data_source is datasource
    assert runtime.generated_executor_provider is provider


def test_read_only_generated_api_does_not_require_generated_executor_provider() -> None:
    builder = ApplicationBuilder()
    builder.add_resource(_resource(ApiExposure.READ_ONLY), FakeDataSource())

    compiled = compile_application(builder)

    assert compiled.generated_resource_executor_providers == ()


def test_crud_generated_api_requires_resource_level_generated_executor_provider() -> None:
    builder = ApplicationBuilder()
    _register_write_capabilities(builder)
    builder.add_resource(_resource(ApiExposure.CRUD), FakeDataSource())

    with pytest.raises(RakitError) as captured:
        compile_application(builder)

    assert captured.value.details == {
        "resource_id": "users",
        "reason": "generated_api_executor_not_supported",
    }


def test_compiled_application_retains_generated_executor_provider() -> None:
    builder = ApplicationBuilder()
    _register_write_capabilities(builder)
    provider = FakeProvider()
    builder.add_resource(
        _resource(ApiExposure.CRUD),
        FakeDataSource(),
        generated_executor_provider=provider,
    )

    compiled = compile_application(builder)

    assert compiled.generated_resource_executor_providers == (("users", provider),)


def test_plugin_rollback_restores_generated_executor_provider_state() -> None:
    provider = FakeProvider()
    builder = ApplicationBuilder()

    class BrokenPlugin:
        plugin_id = "broken-runtime"

        def configure(self, builder: ApplicationBuilder) -> None:
            builder.add_resource(
                _resource(ApiExposure.READ_ONLY),
                FakeDataSource(),
                generated_executor_provider=provider,
            )
            raise RuntimeError("boom")

    with pytest.raises(RuntimeError, match="boom"):
        builder.install(BrokenPlugin())

    assert builder.resources == ()
    assert builder.generated_resource_executor_providers == ()
