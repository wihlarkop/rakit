from rakit_core.definitions import ResourceFieldPolicy
from rakit_core.generated_runtime import ResourceAdapterRuntime
from rakit_sqlalchemy.datasource import SQLAlchemyDataSource
from rakit_sqlalchemy.generated import SQLAlchemyGeneratedResourceExecutorProvider
from rakit_sqlalchemy.plugin import SQLAlchemyPlugin
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "generated_plugin_users"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str]


def test_sqlalchemy_adapter_claim_includes_generated_executor_provider() -> None:
    plugin = SQLAlchemyPlugin(session_factory=async_sessionmaker[AsyncSession]())

    runtime = plugin._claim(
        User,
        ResourceFieldPolicy(
            list_fields=("id", "email"),
            detail_fields=("id", "email"),
        ),
    )

    assert isinstance(runtime, ResourceAdapterRuntime)
    assert isinstance(runtime.data_source, SQLAlchemyDataSource)
    assert isinstance(
        runtime.generated_executor_provider,
        SQLAlchemyGeneratedResourceExecutorProvider,
    )
