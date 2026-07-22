from rakit_core.compiler import ApplicationBuilder
from rakit_core.datasource import DataSource
from rakit_core.definitions import ResourceFieldPolicy
from rakit_core.di import ServiceScope
from rakit_core.errors import ErrorCode, RakitError
from sqlalchemy.exc import NoInspectionAvailable
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from .datasource import SQLAlchemyDataSource
from .introspection import UnsupportedFieldPolicyError, UnsupportedIdentityError, inspect_model


class SQLAlchemyPlugin:
    plugin_id = "sqlalchemy"

    def __init__(self, *, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    def configure(self, builder: ApplicationBuilder) -> None:
        builder.registry.add_value(
            async_sessionmaker, self._session_factory, scope=ServiceScope.APPLICATION
        )
        builder.register_adapter("sqlalchemy", self._claim)

    def _claim(
        self,
        model: type[object],
        field_policy: ResourceFieldPolicy,
    ) -> DataSource | None:
        try:
            inspect_model(model)
        except NoInspectionAvailable:
            return None
        except UnsupportedIdentityError as exc:
            raise RakitError(
                code=ErrorCode.CONFIG_UNSUPPORTED_IDENTITY,
                message=(
                    "SQLAlchemy resources require one Integer, String, or UUID identity column."
                ),
                status_code=500,
                details={"model": model.__name__, "reason": exc.reason},
                cause=exc,
            ) from exc

        try:
            return SQLAlchemyDataSource(
                model=model,
                session_factory=self._session_factory,
                field_policy=field_policy,
            )
        except UnsupportedFieldPolicyError as exc:
            raise RakitError(
                code=ErrorCode.CONFIG_UNSUPPORTED_FIELD_POLICY,
                message=(
                    f'Field "{exc.field}" declared in "{exc.policy}" has no supported query '
                    "semantics for that purpose."
                ),
                status_code=500,
                details={"model": model.__name__, "field": exc.field, "policy": exc.policy},
                cause=exc,
            ) from exc
