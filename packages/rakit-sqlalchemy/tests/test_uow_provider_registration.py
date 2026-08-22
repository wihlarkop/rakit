from rakit_core.compiler import ApplicationBuilder
from rakit_core.definitions import ResourceFieldPolicy
from rakit_core.di import ServiceKey
from rakit_core.generated_runtime import ResourceAdapterRuntime
from rakit_core.transactions import OperationUnitOfWorkFactory
from rakit_sqlalchemy.plugin import SQLAlchemyPlugin
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "uow_provider_users"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str]


def test_sqlalchemy_plugin_registers_named_uow_provider_without_global_di_service() -> None:
    builder = ApplicationBuilder()
    plugin = SQLAlchemyPlugin(session_factory=async_sessionmaker[AsyncSession]())

    builder.install(plugin)

    factories = dict(builder.unit_of_work_factories)
    assert tuple(factories) == ("persistence.sqlalchemy",)
    assert ServiceKey(OperationUnitOfWorkFactory, None) not in builder.registry.providers


def test_sqlalchemy_claim_binds_runtime_to_its_uow_provider() -> None:
    plugin = SQLAlchemyPlugin(session_factory=async_sessionmaker[AsyncSession]())

    runtime = plugin._claim(
        User,
        ResourceFieldPolicy(
            list_fields=("id", "email"),
            detail_fields=("id", "email"),
        ),
    )

    assert isinstance(runtime, ResourceAdapterRuntime)
    assert runtime.unit_of_work_provider_id == "persistence.sqlalchemy"
