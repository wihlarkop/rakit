import pytest

from rakit_core.capabilities import CapabilityProvider, CapabilitySet
from rakit_core.compiler import ApplicationBuilder, compile_application
from rakit_core.datasource import DataSourceCapabilities
from rakit_core.definitions import ResourceDefinition, ResourceFieldPolicy
from rakit_core.errors import RakitError
from rakit_core.fields import FieldDefinition
from rakit_core.generated_api import ApiExposure, GeneratedCrudOperation, ResourceApiDefinition
from rakit_core.query import PageResult


FIELD_DEFINITIONS = (
    FieldDefinition("id", int, readable=True, writable=False),
    FieldDefinition("email", str, required=True, nullable=False),
    FieldDefinition("status", str, required=False, nullable=False),
    FieldDefinition("created_at", str, readable=True, writable=False),
)


class FakeDataSource:
    fields = ("id", "email", "status", "created_at")
    identity_fields = ("id",)
    field_definitions = FIELD_DEFINITIONS

    def __init__(self, capabilities: DataSourceCapabilities) -> None:
        self.capabilities = capabilities

    async def list(self, query):
        return PageResult((), 1, 25, False, False, 0)

    async def count(self, query):
        return 0

    async def detail(self, identity):
        return None


class MetadataLessDataSource(FakeDataSource):
    field_definitions = None


def _resource(api: ResourceApiDefinition) -> ResourceDefinition:
    return ResourceDefinition(
        resource_id="users",
        path="/users",
        label="Users",
        singular_label="User",
        field_policy=ResourceFieldPolicy(
            list_fields=("id", "email"),
            detail_fields=("id", "email", "status", "created_at"),
            filter_fields=("status",),
            search_fields=("email",),
            sort_fields=("email", "created_at"),
        ),
        api=api,
    )


def test_none_exposure_compiles_no_generated_api_projection() -> None:
    builder = ApplicationBuilder()
    builder.add_resource(_resource(ResourceApiDefinition()), FakeDataSource(DataSourceCapabilities()))

    compiled = compile_application(builder)

    assert compiled.compiled_resource_apis == ()


def test_read_only_projection_compiles_without_write_capabilities_or_field_metadata() -> None:
    builder = ApplicationBuilder()
    builder.add_resource(
        _resource(
            ResourceApiDefinition(
                exposure=ApiExposure.READ_ONLY,
                read_fields=("id", "email", "status"),
            )
        ),
        MetadataLessDataSource(DataSourceCapabilities(read=True)),
    )

    compiled = compile_application(builder)

    api = compiled.compiled_resource_apis[0]
    assert api.resource_id == "users"
    assert api.operations == (
        GeneratedCrudOperation.LIST,
        GeneratedCrudOperation.DETAIL,
    )
    assert api.read_fields == ("id", "email", "status")
    assert api.create_fields == ()
    assert api.update_fields == ()
    assert api.field_definitions == ()


def test_crud_projection_requires_create_update_delete_and_transactions() -> None:
    builder = ApplicationBuilder()
    builder.add_resource(
        _resource(
            ResourceApiDefinition(
                exposure=ApiExposure.CRUD,
                read_fields=("id", "email"),
                create_fields=("email",),
                update_fields=("email", "status"),
            )
        ),
        FakeDataSource(DataSourceCapabilities(read=True, create=True, update=True, delete=True)),
    )

    with pytest.raises(RakitError) as captured:
        compile_application(builder)

    assert captured.value.details == {
        "resource_id": "users",
        "reason": "generated_api_transactions_not_supported",
    }


def test_crud_projection_requires_neutral_field_metadata() -> None:
    builder = ApplicationBuilder()
    builder.add_resource(
        _resource(
            ResourceApiDefinition(
                exposure=ApiExposure.CRUD,
                read_fields=("id", "email"),
                create_fields=("email",),
                update_fields=("email", "status"),
            )
        ),
        MetadataLessDataSource(
            DataSourceCapabilities(
                read=True,
                create=True,
                update=True,
                delete=True,
                transactions=True,
            )
        ),
    )

    with pytest.raises(RakitError) as captured:
        compile_application(builder)

    assert captured.value.details == {
        "resource_id": "users",
        "reason": "generated_api_field_metadata_not_supported",
    }


def test_crud_projection_rejects_identity_and_unknown_mutation_fields() -> None:
    capabilities = DataSourceCapabilities(
        read=True,
        create=True,
        update=True,
        delete=True,
        transactions=True,
    )

    identity_builder = ApplicationBuilder()
    identity_builder.add_resource(
        _resource(
            ResourceApiDefinition(
                exposure=ApiExposure.CRUD,
                read_fields=("id", "email"),
                create_fields=("id", "email"),
                update_fields=("email",),
            )
        ),
        FakeDataSource(capabilities),
    )
    with pytest.raises(RakitError) as identity_error:
        compile_application(identity_builder)
    assert identity_error.value.details["reason"] == "generated_api_identity_field_writable"

    unknown_builder = ApplicationBuilder()
    unknown_builder.add_resource(
        _resource(
            ResourceApiDefinition(
                exposure=ApiExposure.CRUD,
                read_fields=("id", "email"),
                create_fields=("email",),
                update_fields=("missing",),
            )
        ),
        FakeDataSource(capabilities),
    )
    with pytest.raises(RakitError) as unknown_error:
        compile_application(unknown_builder)
    assert unknown_error.value.details["reason"] == "generated_api_unknown_field"


def test_compiled_crud_snapshots_neutral_field_metadata() -> None:
    builder = ApplicationBuilder()
    builder.add_resource(
        _resource(
            ResourceApiDefinition(
                exposure=ApiExposure.CRUD,
                read_fields=("id", "email"),
                create_fields=("email",),
                update_fields=("email", "status"),
            )
        ),
        FakeDataSource(
            DataSourceCapabilities(
                read=True,
                create=True,
                update=True,
                delete=True,
                transactions=True,
            )
        ),
    )

    compiled = compile_application(builder)

    assert compiled.compiled_resource_apis[0].field_definitions == FIELD_DEFINITIONS


def test_custom_input_schema_requires_schema_validation_capability() -> None:
    class CreateSchema:
        pass

    capabilities = DataSourceCapabilities(
        read=True,
        create=True,
        update=True,
        delete=True,
        transactions=True,
    )
    builder = ApplicationBuilder()
    builder.add_resource(
        _resource(
            ResourceApiDefinition(
                exposure=ApiExposure.CRUD,
                read_fields=("id", "email"),
                create_fields=("email",),
                update_fields=("email",),
                create_schema=CreateSchema,
            )
        ),
        FakeDataSource(capabilities),
    )

    with pytest.raises(RakitError) as captured:
        compile_application(builder)
    assert captured.value.details["reason"] == "missing_capabilities"
    assert captured.value.details["missing"] == ["schema.input-validation"]

    satisfied = ApplicationBuilder()
    satisfied.register_capability_provider(
        CapabilityProvider("schema.example", CapabilitySet.of("schema.input-validation"))
    )
    satisfied.add_resource(
        _resource(
            ResourceApiDefinition(
                exposure=ApiExposure.CRUD,
                read_fields=("id", "email"),
                create_fields=("email",),
                update_fields=("email",),
                create_schema=CreateSchema,
            )
        ),
        FakeDataSource(capabilities),
    )

    compiled = compile_application(satisfied)
    assert tuple(req.requirement_id for req in compiled.capability_requirements) == (
        "generated-api:users:schema-input",
    )
