import pytest
from pydantic import ValidationError
from rakit import Admin, ModelAdmin, ResourceAdmin, SecretValue
from rakit_core.datasource import DataSourceCapabilities
from rakit_core.errors import ErrorCode, RakitError
from rakit_core.identity import RecordIdentity
from rakit_core.query import PageResult, ResourceQuery
from rakit_sqlalchemy.plugin import SQLAlchemyPlugin
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str]


class UserAdmin(ModelAdmin):
    model = User
    resource_id = "users"
    path = "/users"
    label = "Users"
    singular_label = "User"
    list_fields = ("id", "name")
    detail_fields = ("id", "name")
    filter_fields = ("id", "name")
    search_fields = ("name",)
    sort_fields = ("id", "name")


class IncompleteAdmin(ModelAdmin):
    model = User
    resource_id = "incomplete"
    path = "/incomplete"
    label = "Incomplete"
    list_fields = ("id", "name")
    detail_fields = ("id", "name")
    # singular_label intentionally omitted


class FakeDataSource:
    capabilities = DataSourceCapabilities(read=True)
    fields = ("id", "name")
    identity_fields = ("id",)

    async def list(self, query: ResourceQuery) -> PageResult:
        return PageResult(
            items=({"id": 1, "name": "Ada"},),
            page=1,
            per_page=25,
            has_previous=False,
            has_next=False,
            total_count=1,
        )

    async def count(self, query: ResourceQuery) -> int:
        return 1

    async def detail(self, identity: RecordIdentity):
        return {"id": identity.values["id"], "name": "Ada"}


class ReportAdmin(ResourceAdmin):
    resource_id = "reports"
    path = "/reports"
    label = "Reports"
    singular_label = "Report"
    data_source = FakeDataSource()
    list_fields = ("id", "name")
    detail_fields = ("id", "name")


@pytest.fixture
def session_factory() -> async_sessionmaker[AsyncSession]:
    # Engine creation is lazy (no connection opened) -- these tests only
    # exercise registration/compilation, none of which touches the database.
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    return async_sessionmaker(engine, expire_on_commit=False)


def _make_admin() -> Admin:
    return Admin(title="Operations", debug=False, secret_key=SecretValue("x" * 32))


def test_model_admin_compiles(session_factory) -> None:
    admin = _make_admin()
    admin.install(SQLAlchemyPlugin(session_factory=session_factory))

    admin.register(UserAdmin)

    assert admin.compile().resources[0].resource_id == "users"
    assert "users" in admin._resource_services


def test_model_admin_registration_fails_with_zero_adapters() -> None:
    admin = _make_admin()

    with pytest.raises(RakitError) as exc_info:
        admin.register(UserAdmin)

    assert exc_info.value.code == ErrorCode.CONFIG_ADAPTER_NOT_FOUND


def test_model_admin_registration_fails_with_ambiguous_adapters(session_factory) -> None:
    admin = _make_admin()
    admin.install(SQLAlchemyPlugin(session_factory=session_factory))
    admin._builder.register_adapter("sqlalchemy-2", lambda model, policy: FakeDataSource())

    with pytest.raises(RakitError) as exc_info:
        admin.register(UserAdmin)

    assert exc_info.value.code == ErrorCode.CONFIG_ADAPTER_AMBIGUOUS


def test_register_after_compile_raises() -> None:
    admin = _make_admin()
    admin.compile()

    with pytest.raises(RuntimeError):
        admin.register(UserAdmin)


def test_register_with_missing_attribute_raises() -> None:
    admin = _make_admin()

    with pytest.raises(RakitError) as exc_info:
        admin.register(IncompleteAdmin)

    assert exc_info.value.code == ErrorCode.VALIDATION_FAILED


def test_resource_admin_with_direct_data_source_compiles() -> None:
    admin = _make_admin()

    admin.register(ReportAdmin)

    assert admin.compile().resources[0].resource_id == "reports"
    assert "reports" in admin._resource_services


def test_compiled_field_policy_is_copied_and_immutable() -> None:
    declared_list_fields = ["id"]

    class ImmutablePolicyAdmin(ResourceAdmin):
        resource_id = "immutable_policy"
        path = "/immutable-policy"
        label = "Immutable Policies"
        singular_label = "Immutable Policy"
        data_source = FakeDataSource()
        list_fields = declared_list_fields
        detail_fields = ("id", "name")

    admin = _make_admin()
    admin.register(ImmutablePolicyAdmin)
    declared_list_fields.append("name")

    policy = admin.compile().resources[0].field_policy

    assert policy.list_fields == ("id",)
    with pytest.raises(ValidationError):
        policy.list_fields = ("name",)  # ty: ignore[invalid-assignment]


@pytest.mark.parametrize(
    ("policy_name", "policy_fields", "reason"),
    (
        ("list_fields", ("id", "password_hash"), "unknown_field"),
        ("list_fields", (), "fields_empty"),
        ("detail_fields", (), "fields_empty"),
        ("filter_fields", ("name", "name"), "fields_not_unique"),
        ("search_fields", ("unknown",), "unknown_field"),
        ("sort_fields", ("unknown",), "unknown_field"),
    ),
)
def test_compile_rejects_invalid_policy_with_stable_error(
    policy_name: str,
    policy_fields: tuple[str, ...],
    reason: str,
) -> None:
    class InvalidPolicyAdmin(ResourceAdmin):
        resource_id = "unknown_policy"
        path = "/unknown-policy"
        label = "Unknown Policies"
        singular_label = "Unknown Policy"
        data_source = FakeDataSource()
        list_fields = ("id",)
        detail_fields = ("id",)

    setattr(InvalidPolicyAdmin, policy_name, policy_fields)
    admin = _make_admin()
    admin.register(InvalidPolicyAdmin)

    with pytest.raises(RakitError) as exc_info:
        admin.compile()

    assert exc_info.value.code == ErrorCode.CONFIG_INVALID_RESOURCE_POLICY
    assert exc_info.value.details == {
        "resource_id": "unknown_policy",
        "policy": policy_name,
        "reason": reason,
    }


@pytest.mark.parametrize(
    ("data_source", "reason"),
    [
        (
            type(
                "UnreadableDataSource",
                (FakeDataSource,),
                {"capabilities": DataSourceCapabilities(read=False)},
            )(),
            "read_not_supported",
        ),
        (
            type("DuplicateFieldsDataSource", (FakeDataSource,), {"fields": ("id", "id")})(),
            "fields_not_unique",
        ),
        (
            type("MissingIdentityDataSource", (FakeDataSource,), {"identity_fields": ()})(),
            "identity_fields_empty",
        ),
        (type("EmptyFieldsDataSource", (FakeDataSource,), {"fields": ()})(), "fields_empty"),
        (
            type(
                "DuplicateIdentityDataSource",
                (FakeDataSource,),
                {"identity_fields": ("id", "id")},
            )(),
            "identity_fields_not_unique",
        ),
        (
            type(
                "UnknownIdentityDataSource",
                (FakeDataSource,),
                {"identity_fields": ("unknown",)},
            )(),
            "identity_fields_unknown",
        ),
        (type("MissingCountDataSource", (FakeDataSource,), {"count": None})(), "missing_count"),
        (
            type("InvalidFieldsDataSource", (FakeDataSource,), {"fields": ("id", 1)})(),
            "fields_invalid",
        ),
        (
            type(
                "InvalidIdentityFieldsDataSource",
                (FakeDataSource,),
                {"identity_fields": (1,)},
            )(),
            "identity_fields_invalid",
        ),
    ],
)
def test_compile_rejects_invalid_datasource_contract(
    data_source: FakeDataSource,
    reason: str,
) -> None:
    class InvalidDataSourceAdmin(ResourceAdmin):
        resource_id = "invalid_source"
        path = "/invalid-source"
        label = "Invalid Sources"
        singular_label = "Invalid Source"
        list_fields = ("id",)
        detail_fields = ("id",)

    InvalidDataSourceAdmin.data_source = data_source
    admin = _make_admin()
    admin.register(InvalidDataSourceAdmin)

    with pytest.raises(RakitError) as exc_info:
        admin.compile()

    assert exc_info.value.code == ErrorCode.CONFIG_INVALID_DATASOURCE
    assert exc_info.value.details == {
        "resource_id": "invalid_source",
        "reason": reason,
    }


def test_resource_admin_without_data_source_or_model_raises() -> None:
    class BrokenAdmin(ResourceAdmin):
        resource_id = "broken"
        path = "/broken"
        label = "Broken"
        singular_label = "Broken"
        list_fields = ("id",)
        detail_fields = ("id",)

    admin = _make_admin()

    with pytest.raises(RakitError) as exc_info:
        admin.register(BrokenAdmin)

    assert exc_info.value.code == ErrorCode.CONFIG_RESOURCE_MISSING_DATA_SOURCE


def test_root_resource_collides_with_compiled_builtin_home_route() -> None:
    class RootAdmin(ResourceAdmin):
        resource_id = "root_records"
        path = "/"
        label = "Root Records"
        singular_label = "Root Record"
        data_source = FakeDataSource()
        list_fields = ("id", "name")
        detail_fields = ("id", "name")

    admin = _make_admin()
    admin.register(RootAdmin)

    with pytest.raises(RakitError) as exc_info:
        admin.compile()

    assert exc_info.value.code == ErrorCode.CONFIG_ROUTE_COLLISION


@pytest.mark.parametrize("reverse_registration", (False, True))
def test_overlapping_resource_routes_fail_independent_of_registration_order(
    reverse_registration: bool,
) -> None:
    class ParentAdmin(ResourceAdmin):
        resource_id = "parents"
        path = "/users"
        label = "Parents"
        singular_label = "Parent"
        data_source = FakeDataSource()
        list_fields = ("id", "name")
        detail_fields = ("id", "name")

    class SettingsAdmin(ResourceAdmin):
        resource_id = "settings"
        path = "/users/settings"
        label = "Settings"
        singular_label = "Setting"
        data_source = FakeDataSource()
        list_fields = ("id", "name")
        detail_fields = ("id", "name")

    classes = (SettingsAdmin, ParentAdmin) if reverse_registration else (ParentAdmin, SettingsAdmin)
    admin = _make_admin()
    for admin_class in classes:
        admin.register(admin_class)

    with pytest.raises(RakitError) as exc_info:
        admin.compile()

    assert exc_info.value.code == ErrorCode.CONFIG_ROUTE_COLLISION
