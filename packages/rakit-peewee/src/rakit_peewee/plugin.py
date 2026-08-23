from peewee import Model
from playhouse.pwasyncio import AsyncDatabaseMixin
from rakit_core.compiler import ApplicationBuilder
from rakit_core.definitions import ResourceFieldPolicy
from rakit_core.errors import ErrorCode, RakitError
from rakit_core.generated_runtime import ResourceAdapterRuntime
from rakit_core.integrations import ConfiguredIntegration

from .capabilities import PEEWEE_CAPABILITIES
from .datasource import PeeweeDataSource
from .discovery import PEEWEE_INTEGRATION
from .generated import PeeweeGeneratedResourceExecutorProvider
from .introspection import (
    MismatchedPeeweeDatabaseError,
    UnsupportedPeeweeAsyncDatabaseError,
    UnsupportedPeeweeFieldPolicyError,
    UnsupportedPeeweeIdentityError,
    inspect_model,
    is_peewee_model,
)
from .uow import PeeweeOperationUnitOfWorkFactory


class PeeweePlugin:
    plugin_id = "peewee"
    provider_id = "persistence.peewee"

    def __init__(self, *, database: AsyncDatabaseMixin) -> None:
        if not isinstance(database, AsyncDatabaseMixin):
            raise TypeError("database must use playhouse.pwasyncio.AsyncDatabaseMixin")
        self._database = database

    def configure(self, builder: ApplicationBuilder) -> None:
        builder.register_capability_provider(PEEWEE_CAPABILITIES)
        builder.register_configured_integration(
            ConfiguredIntegration.from_descriptor(PEEWEE_INTEGRATION)
        )
        builder.register_unit_of_work_factory(
            self.provider_id,
            PeeweeOperationUnitOfWorkFactory(database=self._database),
        )
        builder.register_adapter("peewee", self._claim)

    def _claim(
        self,
        subject: object,
        field_policy: ResourceFieldPolicy,
    ) -> ResourceAdapterRuntime | None:
        if not is_peewee_model(subject):
            return None
        model = subject
        assert isinstance(model, type) and issubclass(model, Model)
        try:
            metadata = inspect_model(model, database=self._database)
        except UnsupportedPeeweeAsyncDatabaseError as exc:
            raise RakitError(
                code=ErrorCode.CONFIG_INVALID,
                message="Peewee resources must use the official asyncio database layer.",
                status_code=500,
                details={"model": model.__name__, "reason": "peewee_async_database_required"},
                cause=exc,
            ) from exc
        except MismatchedPeeweeDatabaseError as exc:
            raise RakitError(
                code=ErrorCode.CONFIG_INVALID,
                message="Peewee resource database does not match PeeweePlugin.",
                status_code=500,
                details={"model": model.__name__, "reason": "peewee_database_mismatch"},
                cause=exc,
            ) from exc
        except UnsupportedPeeweeIdentityError as exc:
            raise RakitError(
                code=ErrorCode.CONFIG_UNSUPPORTED_IDENTITY,
                message="Peewee resources require one int, str, or UUID primary key.",
                status_code=500,
                details={"model": model.__name__},
                cause=exc,
            ) from exc

        try:
            data_source = PeeweeDataSource(
                model=metadata.model,
                database=self._database,
                field_policy=field_policy,
            )
        except UnsupportedPeeweeFieldPolicyError as exc:
            raise RakitError(
                code=ErrorCode.CONFIG_UNSUPPORTED_FIELD_POLICY,
                message=(
                    f'Field "{exc.field}" declared in "{exc.policy}" has no supported '
                    "Peewee query semantics."
                ),
                status_code=500,
                details={"model": model.__name__, "field": exc.field, "policy": exc.policy},
                cause=exc,
            ) from exc
        return ResourceAdapterRuntime(
            data_source=data_source,
            generated_executor_provider=PeeweeGeneratedResourceExecutorProvider(
                model=metadata.model,
                data_source=data_source,
            ),
            unit_of_work_provider_id=self.provider_id,
        )


__all__ = ["PeeweePlugin"]
