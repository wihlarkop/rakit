from rakit_core.compiler import ApplicationBuilder
from rakit_core.definitions import ResourceFieldPolicy
from rakit_core.errors import ErrorCode, RakitError
from rakit_core.generated_runtime import ResourceAdapterRuntime
from rakit_core.integrations import ConfiguredIntegration
from sqlalchemy import Table
from sqlalchemy.ext.asyncio import AsyncEngine

from .capabilities import SQLALCHEMY_CORE_CAPABILITIES
from .core_datasource import SQLAlchemyCoreDataSource, inspect_table
from .core_generated import SQLAlchemyCoreGeneratedResourceExecutorProvider
from .core_uow import SQLAlchemyCoreOperationUnitOfWorkFactory
from .core_write import SQLAlchemyCoreWriteServiceProvider
from .discovery import SQLALCHEMY_CORE_INTEGRATION
from .introspection import UnsupportedFieldPolicyError, UnsupportedIdentityError


class SQLAlchemyCorePlugin:
    plugin_id = "sqlalchemy-core"
    provider_id = "persistence.sqlalchemy-core"

    def __init__(self, *, engine: AsyncEngine) -> None:
        self._engine = engine

    def configure(self, builder: ApplicationBuilder) -> None:
        builder.register_capability_provider(SQLALCHEMY_CORE_CAPABILITIES)
        builder.register_configured_integration(
            ConfiguredIntegration.from_descriptor(SQLALCHEMY_CORE_INTEGRATION)
        )
        builder.register_unit_of_work_factory(
            self.provider_id,
            SQLAlchemyCoreOperationUnitOfWorkFactory(self._engine),
        )
        builder.register_adapter("sqlalchemy-core", self._claim)

    def _claim(
        self,
        subject: object,
        field_policy: ResourceFieldPolicy,
    ) -> ResourceAdapterRuntime | None:
        if not isinstance(subject, Table):
            return None

        try:
            inspect_table(subject)
            data_source = SQLAlchemyCoreDataSource(
                table=subject,
                engine=self._engine,
                field_policy=field_policy,
            )
        except UnsupportedIdentityError as exc:
            raise RakitError(
                code=ErrorCode.CONFIG_UNSUPPORTED_IDENTITY,
                message=(
                    "SQLAlchemy Core resources require one Integer, String, or UUID identity "
                    "column."
                ),
                status_code=500,
                details={"table": subject.name, "reason": exc.reason},
                cause=exc,
            ) from exc
        except UnsupportedFieldPolicyError as exc:
            raise RakitError(
                code=ErrorCode.CONFIG_UNSUPPORTED_FIELD_POLICY,
                message=(
                    f'Field "{exc.field}" declared in "{exc.policy}" has no supported query '
                    "semantics for that purpose."
                ),
                status_code=500,
                details={"table": subject.name, "field": exc.field, "policy": exc.policy},
                cause=exc,
            ) from exc

        return ResourceAdapterRuntime(
            data_source=data_source,
            generated_executor_provider=SQLAlchemyCoreGeneratedResourceExecutorProvider(
                data_source=data_source
            ),
            write_service_provider=SQLAlchemyCoreWriteServiceProvider(
                data_source=data_source,
                engine=self._engine,
            ),
            unit_of_work_provider_id=self.provider_id,
        )


__all__ = ["SQLAlchemyCorePlugin"]
