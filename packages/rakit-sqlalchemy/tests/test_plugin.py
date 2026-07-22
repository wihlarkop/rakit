import pytest
from rakit_core.compiler import ApplicationBuilder
from rakit_core.definitions import ResourceFieldPolicy
from rakit_core.di import ServiceScope
from rakit_sqlalchemy.datasource import SQLAlchemyDataSource
from rakit_sqlalchemy.plugin import SQLAlchemyPlugin
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str]


class NotAModel:
    pass


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
