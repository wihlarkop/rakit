from rakit_core.compiler import ApplicationBuilder
from rakit_core.definitions import ResourceFieldPolicy
from rakit_core.di import ServiceScope
from rakit_core.errors import ErrorCode, RakitError
from rakit_core.generated_runtime import ResourceAdapterRuntime
from rakit_core.integrations import ConfiguredIntegration
from sqlalchemy.exc import NoInspectionAvailable
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from .capabilities import SQLALCHEMY_CAPABILITIES
from .datasource import SQLAlchemyDataSource
from .discovery import SQLALCHEMY_INTEGRATION
from .generated import SQLAlchemyGeneratedResourceExecutorProvider
from .introspection import UnsupportedFieldPolicyError, UnsupportedIdentityError, inspect_model
from .uow import SQLAlchemyOperationUnitOfWorkFactory
from .write_provider import SQLAlchemyWriteServiceProvider


class SQLAlchemyPlugin:
    plugin_id = "sqlalchemy"
    unit_of_work_provider_id = "persistence.sqlalchemy"

    def __init__(self, *, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    def configure(self, builder: ApplicationBuilder) -> None:
        builder.register_capability_provider(SQLALCHEMY_CAPABILITIES)
        builder.register_configured_integration(
            ConfiguredIntegration.from_descriptor(SQLALCHEMY_INTEGRATION)
        )
        builder.registry.add_value(
            async_sessionmaker, self._session_factory, scope=ServiceScope.APPLICATION
        )
        builder.register_unit_of_work_factory(
            self.unit_of_work_provider_id,
            SQLAlchemyOperationUnitOfWorkFactory(self._session_factory),
        )
        builder.register_adapter("sqlalchemy", self._claim)

    def _claim(
        self,
        subject: object,
        field_policy: ResourceFieldPolicy,
    ) -> ResourceAdapterRuntime | None:
        if not isinstance(subject, type):
            return None
        model = subject
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
            data_source = SQLAlchemyDataSource(
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
        return ResourceAdapterRuntime(
            data_source=data_source,
            generated_executor_provider=SQLAlchemyGeneratedResourceExecutorProvider(model=model),
            write_service_provider=SQLAlchemyWriteServiceProvider(
                model=model,
                session_factory=self._session_factory,
            ),
            unit_of_work_provider_id=self.unit_of_work_provider_id,
        )
