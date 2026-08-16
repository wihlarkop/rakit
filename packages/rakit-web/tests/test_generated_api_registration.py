from rakit import ApiExposure, ResourceAdmin, ResourceApiDefinition
from rakit_core.datasource import DataSourceCapabilities
from rakit_core.query import PageResult
from rakit_web.admin import Admin


class DataSource:
    capabilities = DataSourceCapabilities(read=True)
    fields = ("id", "email")
    identity_fields = ("id",)

    async def list(self, query):
        return PageResult((), 1, 25, False, False, 0)

    async def count(self, query):
        return 0

    async def detail(self, identity):
        return None


class UserAdmin(ResourceAdmin):
    resource_id = "users"
    path = "/users"
    label = "Users"
    singular_label = "User"
    list_fields = ("id", "email")
    detail_fields = ("id", "email")
    data_source = DataSource()
    api = ResourceApiDefinition(
        exposure=ApiExposure.READ_ONLY,
        read_fields=("id", "email"),
    )


def test_resource_admin_generated_api_policy_is_copied_to_canonical_definition() -> None:
    admin = Admin(title="Generated API")
    admin.register(UserAdmin)

    definition = admin.builder.resources[0]
    assert definition.api is UserAdmin.api
    assert definition.api.exposure is ApiExposure.READ_ONLY
    assert definition.api.read_fields == ("id", "email")
