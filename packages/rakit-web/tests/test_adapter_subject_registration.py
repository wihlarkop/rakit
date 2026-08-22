from __future__ import annotations

from dataclasses import dataclass

from rakit import Admin, ModelAdmin, SecretValue
from rakit_core.datasource import DataSourceCapabilities
from rakit_core.definitions import ResourceFieldPolicy
from rakit_core.generated_runtime import ResourceAdapterRuntime
from rakit_core.identity import RecordIdentity
from rakit_core.pagination import PageResult, ResourceListResult
from rakit_core.query import ResourceQuery
from rakit_sqlalchemy.plugin import SQLAlchemyPlugin
from rakit_tortoise.plugin import TortoisePlugin
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


@dataclass(frozen=True, slots=True)
class NativeSubject:
    name: str


class NativeDataSource:
    capabilities = DataSourceCapabilities()
    fields = ("id", "name")
    identity_fields = ("id",)

    async def list(self, query: ResourceQuery) -> ResourceListResult[object]:
        return PageResult(
            items=(),
            page=1,
            per_page=25,
            has_previous=False,
            has_next=False,
            total_count=0,
        )

    async def count(self, query: ResourceQuery) -> int:
        return 0

    async def detail(self, identity: RecordIdentity) -> object:
        raise LookupError(identity)


SUBJECT = NativeSubject("native-schema")


class NativeAdmin(ModelAdmin):
    model = SUBJECT
    resource_id = "native_subjects"
    path = "/native-subjects"
    label = "Native subjects"
    singular_label = "Native subject"
    list_fields = ("id", "name")
    detail_fields = ("id", "name")


class SQLAlchemyBase(DeclarativeBase):
    pass


class SQLAlchemySubject(SQLAlchemyBase):
    __tablename__ = "adapter_subject_users"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str]


class SQLAlchemySubjectAdmin(ModelAdmin):
    model = SQLAlchemySubject
    resource_id = "sqlalchemy_subjects"
    path = "/sqlalchemy-subjects"
    label = "SQLAlchemy subjects"
    singular_label = "SQLAlchemy subject"
    list_fields = ("id", "name")
    detail_fields = ("id", "name")


def test_model_admin_accepts_non_class_native_adapter_subject() -> None:
    seen: list[object] = []

    def claim(
        subject: object,
        _field_policy: ResourceFieldPolicy,
    ) -> ResourceAdapterRuntime | None:
        seen.append(subject)
        if subject is not SUBJECT:
            return None
        return ResourceAdapterRuntime(data_source=NativeDataSource())

    admin = Admin(
        title="Native adapter subjects",
        debug=False,
        secret_key=SecretValue("x" * 32),
    )
    admin.builder.register_adapter("native-object", claim)

    admin.register(NativeAdmin)

    assert seen == [SUBJECT]
    assert not isinstance(NativeAdmin.model, type)
    assert admin.compile().resources[0].resource_id == "native_subjects"


def test_class_oriented_first_party_adapters_reject_non_class_subjects() -> None:
    policy = ResourceFieldPolicy(
        list_fields=("id",),
        detail_fields=("id",),
    )
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    assert TortoisePlugin()._claim(SUBJECT, policy) is None
    assert SQLAlchemyPlugin(session_factory=session_factory)._claim(SUBJECT, policy) is None


def test_admin_binds_claimed_resource_to_adapter_uow_provider() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    admin = Admin(
        title="Resource UoW ownership",
        debug=False,
        secret_key=SecretValue("x" * 32),
    )
    admin.builder.install(SQLAlchemyPlugin(session_factory=session_factory))

    admin.register(SQLAlchemySubjectAdmin)

    assert dict(admin.builder.resource_unit_of_work_provider_ids) == {
        "sqlalchemy_subjects": "persistence.sqlalchemy"
    }
    assert dict(admin.compile().resource_unit_of_work_provider_ids) == {
        "sqlalchemy_subjects": "persistence.sqlalchemy"
    }
