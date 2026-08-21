from rakit_core.compiler import ApplicationBuilder
from rakit_core.definitions import ResourceFieldPolicy
from rakit_core.errors import ErrorCode, RakitError
from rakit_core.generated_runtime import ResourceAdapterRuntime
from rakit_core.integrations import ConfiguredIntegration

from .capabilities import TORTOISE_CAPABILITIES
from .datasource import TortoiseDataSource
from .discovery import TORTOISE_INTEGRATION
from .introspection import (
    UnsupportedTortoiseFieldPolicyError,
    UnsupportedTortoiseIdentityError,
    inspect_model,
)


class TortoisePlugin:
    plugin_id = "tortoise"

    def configure(self, builder: ApplicationBuilder) -> None:
        builder.register_capability_provider(TORTOISE_CAPABILITIES)
        builder.register_configured_integration(
            ConfiguredIntegration.from_descriptor(TORTOISE_INTEGRATION)
        )
        builder.register_adapter("tortoise", self._claim)

    def _claim(
        self,
        model: type[object],
        field_policy: ResourceFieldPolicy,
    ) -> ResourceAdapterRuntime | None:
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
        return ResourceAdapterRuntime(data_source=data_source)


__all__ = ["TortoisePlugin"]
