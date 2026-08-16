import pytest
from rakit_core.compiler import ApplicationBuilder, compile_application
from rakit_core.datasource import DataSourceCapabilities
from rakit_core.definitions import ResourceDefinition, ResourceFieldPolicy
from rakit_core.errors import RakitError
from rakit_core.generated_api import ApiExposure, ResourceApiDefinition
from rakit_core.query import PageResult


class ReadDisabledDataSource:
    capabilities = DataSourceCapabilities(read=False)
    fields = ("id", "email")
    identity_fields = ("id",)

    async def list(self, query):
        return PageResult((), 1, 25, False, False, 0)

    async def count(self, query):
        return 0

    async def detail(self, identity):
        return None


def test_generated_read_only_api_rejects_resource_without_read_capability() -> None:
    builder = ApplicationBuilder()
    builder.add_resource(
        ResourceDefinition(
            resource_id="users",
            path="/users",
            label="Users",
            singular_label="User",
            field_policy=ResourceFieldPolicy(
                list_fields=("id", "email"),
                detail_fields=("id", "email"),
            ),
            api=ResourceApiDefinition(
                exposure=ApiExposure.READ_ONLY,
                read_fields=("id", "email"),
            ),
        ),
        ReadDisabledDataSource(),
    )

    with pytest.raises(RakitError) as captured:
        compile_application(builder)

    assert captured.value.details == {
        "resource_id": "users",
        "reason": "generated_api_read_not_supported",
    }
