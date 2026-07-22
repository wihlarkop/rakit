from enum import Enum as PythonEnum
from typing import Any, cast

import pytest
from rakit_core.compiler import ApplicationBuilder
from rakit_core.definitions import ResourceFieldPolicy
from rakit_core.di import ServiceScope
from rakit_core.errors import ErrorCode, RakitError
from rakit_core.identity import RecordIdentity
from rakit_core.query import Filter, FilterOperator, ResourceQuery, Sort
from rakit_sqlalchemy.datasource import SQLAlchemyDataSource
from rakit_sqlalchemy.introspection import inspect_model
from rakit_sqlalchemy.plugin import SQLAlchemyPlugin
from sqlalchemy import BigInteger, Boolean, Date, Numeric, String, Uuid
from sqlalchemy import Enum as SQLAlchemyEnum
from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.types import TypeDecorator


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str]


class NotAModel:
    pass


class RenamedUser(Base):
    __tablename__ = "renamed_users"

    user_id: Mapped[int] = mapped_column("id", primary_key=True)
    display_name: Mapped[str] = mapped_column("name")


class BigIntegerIdentity(Base):
    __tablename__ = "big_integer_identities"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)


class StringIdentity(Base):
    __tablename__ = "string_identities"

    id: Mapped[str] = mapped_column(String, primary_key=True)


class UUIDIdentity(Base):
    __tablename__ = "uuid_identities"

    id: Mapped[object] = mapped_column(Uuid, primary_key=True)


class SafeStringIdentity(TypeDecorator[str]):
    impl = String
    cache_ok = True


class DecoratedIdentity(Base):
    __tablename__ = "decorated_identities"

    id: Mapped[str] = mapped_column(SafeStringIdentity, primary_key=True)


class DateIdentity(Base):
    __tablename__ = "date_identities"

    id: Mapped[object] = mapped_column(Date, primary_key=True)


class BooleanIdentity(Base):
    __tablename__ = "boolean_identities"

    id: Mapped[bool] = mapped_column(Boolean, primary_key=True)


class NumericIdentity(Base):
    __tablename__ = "numeric_identities"

    id: Mapped[object] = mapped_column(Numeric, primary_key=True)


class CompositeIdentity(Base):
    __tablename__ = "composite_identities"

    tenant_id: Mapped[int] = mapped_column(primary_key=True)
    local_id: Mapped[int] = mapped_column(primary_key=True)


class Status(PythonEnum):
    ACTIVE = "active"
    DISABLED = "disabled"


class PythonEnumIdentity(Base):
    """Enum primary key backed by a Python `enum.Enum` class."""

    __tablename__ = "python_enum_identities"

    id: Mapped[Status] = mapped_column(SQLAlchemyEnum(Status), primary_key=True)


class PlainStringEnumIdentity(Base):
    """Enum primary key with no Python `enum.Enum` class -- just a fixed
    string-value whitelist (`sqlalchemy.Enum(*values)`)."""

    __tablename__ = "plain_string_enum_identities"

    id: Mapped[str] = mapped_column(SQLAlchemyEnum("active", "disabled"), primary_key=True)


class Money:
    """A custom domain object a misbehaving `TypeDecorator` might return --
    not one of int/str/UUID, and therefore not encodable by `RecordIdentity`
    or the web identity codec."""

    def __init__(self, cents: int) -> None:
        self.cents = cents


class UnsafeMoneyType(TypeDecorator[Money]):
    """Wraps `String` but hands back a custom domain object, not a `str` --
    exactly the "same problem" a `TypeDecorator` can reintroduce even when
    its declared `impl` unwraps to a supported base type."""

    impl = String
    cache_ok = True

    @property
    def python_type(self) -> type:
        return Money


class UnsafeMoneyIdentity(Base):
    __tablename__ = "unsafe_money_identities"

    id: Mapped[object] = mapped_column(UnsafeMoneyType, primary_key=True)


class ExplicitIdentityCodec:
    def decode(self, raw: object) -> Money:
        assert isinstance(raw, str)
        return Money(int(raw))


class CodecBackedMoneyType(TypeDecorator[Money]):
    """An otherwise-unsafe custom identity type made safe by an explicit,
    opt-in Rakit identity codec -- the only sanctioned way to support a
    genuinely custom identity value type."""

    impl = String
    cache_ok = True
    rakit_identity_codec = ExplicitIdentityCodec()

    @property
    def python_type(self) -> type:
        return Money


class CodecBackedIdentity(Base):
    __tablename__ = "codec_backed_identities"

    id: Mapped[object] = mapped_column(CodecBackedMoneyType, primary_key=True)


@pytest.fixture
def session_factory() -> async_sessionmaker[AsyncSession]:
    # Engine creation is lazy (no connection opened) -- these tests only
    # exercise configure()/claim(), neither of which touches the database,
    # so a plain sync fixture is sufficient here.
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    return async_sessionmaker(engine, expire_on_commit=False)


def test_plugin_configure_registers_adapter_and_session_factory(session_factory) -> None:
    builder = ApplicationBuilder()
    plugin = SQLAlchemyPlugin(session_factory=session_factory)

    plugin.configure(builder)

    assert "sqlalchemy" in builder._adapters
    key = next(key for key in builder.registry.providers if key.service_type is async_sessionmaker)
    scope, _ = builder.registry.providers[key]
    assert scope == ServiceScope.APPLICATION


def test_claim_returns_datasource_for_mapped_model(session_factory) -> None:
    builder = ApplicationBuilder()
    plugin = SQLAlchemyPlugin(session_factory=session_factory)
    plugin.configure(builder)

    claim = builder._adapters["sqlalchemy"]
    datasource = claim(
        User,
        ResourceFieldPolicy(list_fields=("id", "name"), detail_fields=("id", "name")),
    )

    assert isinstance(datasource, SQLAlchemyDataSource)


def test_claim_returns_none_for_non_mapped_class(session_factory) -> None:
    builder = ApplicationBuilder()
    plugin = SQLAlchemyPlugin(session_factory=session_factory)
    plugin.configure(builder)

    claim = builder._adapters["sqlalchemy"]

    assert (
        claim(
            NotAModel,
            ResourceFieldPolicy(list_fields=("id",), detail_fields=("id",)),
        )
        is None
    )


def test_introspection_uses_mapper_attributes_and_retains_database_names() -> None:
    metadata = inspect_model(RenamedUser)

    assert metadata.identity_field == "user_id"
    assert metadata.fields == ("user_id", "display_name")
    assert [(field.attribute_name, field.database_name) for field in metadata.field_metadata] == [
        ("user_id", "id"),
        ("display_name", "name"),
    ]


@pytest.mark.parametrize(
    ("model", "identity_field"),
    (
        (User, "id"),
        (BigIntegerIdentity, "id"),
        (StringIdentity, "id"),
        (UUIDIdentity, "id"),
        (DecoratedIdentity, "id"),
        (CodecBackedIdentity, "id"),
    ),
)
def test_claim_accepts_supported_identity_types(
    session_factory,
    model: type[object],
    identity_field: str,
) -> None:
    plugin = SQLAlchemyPlugin(session_factory=session_factory)
    policy = ResourceFieldPolicy(
        list_fields=(identity_field,),
        detail_fields=(identity_field,),
    )

    datasource = plugin._claim(model, policy)

    assert isinstance(datasource, SQLAlchemyDataSource)


@pytest.mark.parametrize(
    ("model", "reason"),
    (
        (DateIdentity, "unsupported_type"),
        (BooleanIdentity, "unsupported_type"),
        (NumericIdentity, "unsupported_type"),
        (CompositeIdentity, "composite_identity"),
        (PythonEnumIdentity, "unsupported_type"),
        (PlainStringEnumIdentity, "unsupported_type"),
        (UnsafeMoneyIdentity, "unsupported_type"),
    ),
)
def test_claim_rejects_unsupported_identity_with_stable_error(
    session_factory,
    model: type[object],
    reason: str,
) -> None:
    plugin = SQLAlchemyPlugin(session_factory=session_factory)
    policy = ResourceFieldPolicy(list_fields=("id",), detail_fields=("id",))

    with pytest.raises(RakitError) as exc_info:
        plugin._claim(model, policy)

    assert exc_info.value.code == ErrorCode.CONFIG_UNSUPPORTED_IDENTITY
    assert exc_info.value.details == {"model": model.__name__, "reason": reason}


def test_codec_backed_identity_uses_explicit_hook_before_strict_backend_binding(
    session_factory,
) -> None:
    """An accepted custom identity type must actually route through its
    explicit `rakit_identity_codec` hook (not `rakit_coerce_filter_value`,
    and not silent inference) to produce its bound query value."""
    datasource = SQLAlchemyDataSource(
        model=CodecBackedIdentity,
        session_factory=session_factory,
        field_policy=ResourceFieldPolicy(list_fields=("id",), detail_fields=("id",)),
    )

    statement = datasource._detail_statement(RecordIdentity(values={"id": "500"}))
    compiled = statement.compile(dialect=postgresql.dialect())

    assert len(compiled.params) == 1
    bound_value = next(iter(compiled.params.values()))
    assert isinstance(bound_value, Money)
    assert bound_value.cents == 500


class _IdentitySessionFactorySpy:
    def __init__(self) -> None:
        self.calls = 0

    def __call__(self) -> Any:
        self.calls += 1
        raise AssertionError("invalid identities must fail before session creation")


async def test_invalid_codec_backed_identity_is_safe_before_session_creation() -> None:
    factory = _IdentitySessionFactorySpy()
    datasource = SQLAlchemyDataSource(
        model=CodecBackedIdentity,
        session_factory=cast(Any, factory),
        field_policy=ResourceFieldPolicy(list_fields=("id",), detail_fields=("id",)),
    )

    with pytest.raises(RakitError) as exc_info:
        await datasource.detail(RecordIdentity(values={"id": "not-an-integer"}))

    assert exc_info.value.to_public_dict() == {
        "code": "validation.failed",
        "message": "Invalid resource identity",
        "details": {"field": "id"},
    }
    assert factory.calls == 0


def test_renamed_attributes_compile_database_column_names_for_postgresql(
    session_factory,
) -> None:
    policy = ResourceFieldPolicy(
        list_fields=("user_id", "display_name"),
        detail_fields=("user_id", "display_name"),
        filter_fields=("display_name",),
        search_fields=("display_name",),
        sort_fields=("display_name",),
    )
    datasource = SQLAlchemyDataSource(
        model=RenamedUser,
        session_factory=session_factory,
        field_policy=policy,
    )
    query = ResourceQuery(
        filters=(
            Filter(
                field="display_name",
                operator=FilterOperator.CONTAINS,
                value="Ada",
            ),
        ),
        sorting=(Sort(field="display_name"),),
        search="Ada",
    )

    statement = datasource._filtered_statement(query)
    statement = datasource._apply_sort(statement, query.sorting[0])
    compiled = str(statement.compile(dialect=postgresql.dialect()))

    assert "renamed_users.id" in compiled
    assert "renamed_users.name" in compiled
    assert "ORDER BY renamed_users.name ASC" in compiled


async def test_database_column_name_cannot_bypass_attribute_policy(session_factory) -> None:
    datasource = SQLAlchemyDataSource(
        model=RenamedUser,
        session_factory=session_factory,
        field_policy=ResourceFieldPolicy(
            list_fields=("user_id", "display_name"),
            detail_fields=("user_id", "display_name"),
            filter_fields=("display_name",),
        ),
    )
    query = ResourceQuery(
        filters=(Filter(field="name", operator=FilterOperator.EQ, value="Ada"),),
    )

    with pytest.raises(RakitError) as exc_info:
        await datasource.list(query)

    assert exc_info.value.to_public_dict() == {
        "code": "validation.failed",
        "message": "Query field is not allowed",
    }
