from rakit_core.compiler import ApplicationBuilder
from rakit_sqlalchemy.plugin import SQLAlchemyPlugin
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


def test_sqlalchemy_plugin_registers_capability_provider() -> None:
    builder = ApplicationBuilder()
    session_factory = async_sessionmaker[AsyncSession]()

    builder.install(SQLAlchemyPlugin(session_factory=session_factory))

    assert tuple(provider.provider_id for provider in builder.capability_providers) == (
        "persistence.sqlalchemy",
    )
