from rakit_core.compiler import ApplicationBuilder
from rakit_core.definitions import ResourceFieldPolicy
from rakit_core.errors import ErrorCode, RakitError
from rakit_core.generated_runtime import ResourceAdapterRuntime
from rakit_core.integrations import ConfiguredIntegration

from .capabilities import TORTOISE_CAPABILITIES
from .datasource import TortoiseDataSource
from .discovery import TORTOISE_INTEGRATION
from .generated import TortoiseGeneratedResourceExecutorProvider
from .introspection import (
    UnsupportedTortoiseFieldPolicyError,
    UnsupportedTortoiseIdentityError,
    inspect_model,
)
from .uow import TortoiseOperationUnitOfWorkFactory


class TortoisePlugin:
    plugin_id = "tortoise"
    provider_id = "persistence.tortoise"

    def __init__(self, *, connection_name: str = "default") -> None:
        if not connection_name or connection_name != connection_name.strip():
            raise ValueError("connection_name must be a non-empty normalized string")
        self._connection_name = connection_name

    def configure(self, builder: ApplicationBuilder) -> None:
        builder.register_capability_provider(TORTOISE_CAPABILITIES)
        builder.register_configured_integration(
            ConfiguredIntegration.from_descriptor(TORTOISE_INTEGRATION)
        )
        builder.register_unit_of_work_factory(
            self.provider_id,
            TortoiseOperationUnitOfWorkFactory(connection_name=self._connection_name),
        )
        builder.register_adapter("tortoise", self._claim)

    def _claim(
        self,
        subject: object,
        field_policy: ResourceFieldPolicy,
    ) -> ResourceAdapterRuntime | None:
        if not isinstance(subject, type):
            return None
        model = subject
        try:
            metadata = inspect_model(model)
        except TypeError:
            return None
        except UnsupportedTortoiseIdentityError as exc:
            raise RakitError(
                code=ErrorCode.CONFIG_UNSUPPORTED_IDENTITY,
                message="Tortoise resources require one int, str, or UUID primary key.",
                status_code=500,
                details={"model": model.__name__},
                cause=exc,
            ) from exc

        try:
            data_source = TortoiseDataSource(
                model=metadata.model,
                field_policy=field_policy,
            )
        except UnsupportedTortoiseFieldPolicyError as exc:
            raise RakitError(
                code=ErrorCode.CONFIG_UNSUPPORTED_FIELD_POLICY,
                message=(
                    f'Field "{exc.field}" declared in "{exc.policy}" has no supported '
                    "Tortoise query semantics."
                ),
                status_code=500,
                details={"model": model.__name__, "field": exc.field, "policy": exc.policy},
                cause=exc,
            ) from exc
        return ResourceAdapterRuntime(
            data_source=data_source,
            generated_executor_provider=TortoiseGeneratedResourceExecutorProvider(
                model=metadata.model,
                data_source=data_source,
            ),
            unit_of_work_provider_id=self.provider_id,
        )


__all__ = ["TortoisePlugin"]
