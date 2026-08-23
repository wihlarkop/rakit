from piccolo.engine.base import Engine
from piccolo.table import Table
from rakit_core.compiler import ApplicationBuilder
from rakit_core.definitions import ResourceFieldPolicy
from rakit_core.errors import ErrorCode, RakitError
from rakit_core.generated_runtime import ResourceAdapterRuntime
from rakit_core.integrations import ConfiguredIntegration

from .capabilities import PICCOLO_CAPABILITIES
from .datasource import PiccoloDataSource
from .discovery import PICCOLO_INTEGRATION
from .generated import PiccoloGeneratedResourceExecutorProvider
from .introspection import (
    MismatchedPiccoloEngineError,
    UnsupportedPiccoloEngineError,
    UnsupportedPiccoloFieldPolicyError,
    UnsupportedPiccoloIdentityError,
    inspect_model,
    is_piccolo_model,
)
from .uow import PiccoloOperationUnitOfWorkFactory


class PiccoloPlugin:
    plugin_id = "piccolo"
    provider_id = "persistence.piccolo"

    def __init__(self, *, engine: Engine) -> None:
        if not isinstance(engine, Engine):
            raise TypeError("engine must be a Piccolo Engine")
        self._engine = engine

    def configure(self, builder: ApplicationBuilder) -> None:
        builder.register_capability_provider(PICCOLO_CAPABILITIES)
        builder.register_configured_integration(
            ConfiguredIntegration.from_descriptor(PICCOLO_INTEGRATION)
        )
        builder.register_unit_of_work_factory(
            self.provider_id,
            PiccoloOperationUnitOfWorkFactory(engine=self._engine),
        )
        builder.register_adapter("piccolo", self._claim)

    def _claim(
        self,
        subject: object,
        field_policy: ResourceFieldPolicy,
    ) -> ResourceAdapterRuntime | None:
        if not is_piccolo_model(subject):
            return None
        model = subject
        assert isinstance(model, type) and issubclass(model, Table)
        try:
            metadata = inspect_model(model, engine=self._engine)
        except UnsupportedPiccoloEngineError as exc:
            raise RakitError(
                code=ErrorCode.CONFIG_INVALID,
                message="Piccolo resources require a configured engine.",
                status_code=500,
                details={"model": model.__name__, "reason": "piccolo_engine_required"},
                cause=exc,
            ) from exc
        except MismatchedPiccoloEngineError as exc:
            raise RakitError(
                code=ErrorCode.CONFIG_INVALID,
                message="Piccolo resource engine does not match PiccoloPlugin.",
                status_code=500,
                details={"model": model.__name__, "reason": "piccolo_engine_mismatch"},
                cause=exc,
            ) from exc
        except UnsupportedPiccoloIdentityError as exc:
            raise RakitError(
                code=ErrorCode.CONFIG_UNSUPPORTED_IDENTITY,
                message="Piccolo resources require one int, str, or UUID primary key.",
                status_code=500,
                details={"model": model.__name__},
                cause=exc,
            ) from exc

        try:
            data_source = PiccoloDataSource(
                model=metadata.model,
                engine=self._engine,
                field_policy=field_policy,
            )
        except UnsupportedPiccoloFieldPolicyError as exc:
            raise RakitError(
                code=ErrorCode.CONFIG_UNSUPPORTED_FIELD_POLICY,
                message=(
                    f'Field "{exc.field}" declared in "{exc.policy}" has no supported '
                    "Piccolo query semantics."
                ),
                status_code=500,
                details={"model": model.__name__, "field": exc.field, "policy": exc.policy},
                cause=exc,
            ) from exc
        return ResourceAdapterRuntime(
            data_source=data_source,
            generated_executor_provider=PiccoloGeneratedResourceExecutorProvider(
                model=metadata.model,
                data_source=data_source,
            ),
            unit_of_work_provider_id=self.provider_id,
        )


__all__ = ["PiccoloPlugin"]
