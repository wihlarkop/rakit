from rakit_core.compiler import ApplicationBuilder
from rakit_core.datasource import DataSource
from rakit_core.di import ServiceScope
from sqlalchemy.exc import NoInspectionAvailable
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from .datasource import SQLAlchemyDataSource
from .introspection import inspect_model


class SQLAlchemyPlugin:
    plugin_id = "sqlalchemy"

    def __init__(self, *, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    def configure(self, builder: ApplicationBuilder) -> None:
        builder.registry.add_value(
            async_sessionmaker, self._session_factory, scope=ServiceScope.APPLICATION
        )
        builder.register_adapter("sqlalchemy", self._claim)

    def _claim(self, model: type[object]) -> DataSource | None:
        try:
            inspect_model(model)
        except (ValueError, NoInspectionAvailable):
            return None
        return SQLAlchemyDataSource(model=model, session_factory=self._session_factory)
