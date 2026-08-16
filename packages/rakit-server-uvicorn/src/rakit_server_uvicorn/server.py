import importlib
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, ClassVar, cast

import uvicorn
from rakit_server import (
    ASGIApplication,
    ServerCapabilities,
    ServerConfig,
    ServerConfigurationError,
    ServerTarget,
    ServerTargetKind,
    load_application,
    resolve_server_target,
)

_RESERVED_OPTIONS = {"app", "host", "port", "workers", "reload", "log_level"}


def _import_target_value(spec: str) -> object:
    module_name, attribute = spec.split(":", 1)
    try:
        return getattr(importlib.import_module(module_name), attribute)
    except (ImportError, AttributeError) as exc:
        raise ServerConfigurationError(f'Unable to import Uvicorn target "{spec}"') from exc


@dataclass(slots=True)
class UvicornServer:
    app: object | None = None
    host: str = "127.0.0.1"
    port: int = 8000
    workers: int = 1
    reload: bool = False
    log_level: str | None = None
    server_options: Mapping[str, object] = field(default_factory=dict)
    _active_server: uvicorn.Server | None = field(default=None, init=False, repr=False)

    name: ClassVar[str] = "uvicorn"
    capabilities: ClassVar[ServerCapabilities] = ServerCapabilities(
        async_serve=True,
        graceful_stop=True,
        reload=True,
        workers=True,
        app_object=True,
        import_string=True,
    )

    def _default_config(self) -> ServerConfig:
        return ServerConfig(
            host=self.host,
            port=self.port,
            workers=self.workers,
            reload=self.reload,
            log_level=self.log_level,
            server_options=self.server_options,
        )

    def _resolve_target(self, target: ServerTarget | object | None) -> ServerTarget:
        if target is None:
            if self.app is None:
                raise ServerConfigurationError(
                    "UvicornServer.run() requires a target unless app was supplied to the constructor"
                )
            source = self.app
        else:
            if self.app is not None:
                raise ServerConfigurationError(
                    "Uvicorn target cannot be supplied both to the constructor and run()/serve()"
                )
            source = target
        return source if isinstance(source, ServerTarget) else resolve_server_target(source)

    @staticmethod
    def _validate_options(config: ServerConfig) -> dict[str, Any]:
        native = cast(dict[str, Any], dict(config.server_options))
        conflicts = sorted(_RESERVED_OPTIONS.intersection(native))
        if conflicts:
            raise ServerConfigurationError(
                "Uvicorn server_options cannot override portable option(s): "
                + ", ".join(conflicts)
            )
        if config.reload and config.workers > 1:
            raise ServerConfigurationError("Uvicorn reload and multiple workers are mutually exclusive")
        return native

    @staticmethod
    def _resolve_for_run(
        target: ServerTarget, config: ServerConfig, native: Mapping[str, Any]
    ) -> str | ASGIApplication:
        process_mode = config.reload or config.workers > 1
        factory_mode = native.get("factory") is True

        if target.kind is ServerTargetKind.APPLICATION:
            if process_mode or factory_mode:
                raise ServerConfigurationError(
                    "Uvicorn reload, multiple workers, and factory mode require an import-string "
                    "target; use rakit.run(\"module:app\", ...) instead of an application object."
                )
            assert target.application is not None
            return target.application

        assert target.import_string is not None
        if factory_mode:
            return target.import_string
        if not process_mode:
            return load_application(target.import_string)

        imported = _import_target_value(target.import_string)
        if callable(getattr(imported, "asgi", None)):
            raise ServerConfigurationError(
                "Uvicorn reload or multiple workers cannot call asgi() on an imported Admin "
                "object. Export `app = admin.asgi()` and target `module:app` instead."
            )
        if not callable(imported):
            raise ServerConfigurationError(
                f'Uvicorn import target "{target.import_string}" is not callable'
            )
        return target.import_string

    @staticmethod
    def _resolve_for_async_serve(
        target: ServerTarget, native: Mapping[str, Any]
    ) -> str | ASGIApplication:
        if target.kind is ServerTargetKind.APPLICATION:
            if native.get("factory") is True:
                raise ServerConfigurationError("Uvicorn factory mode requires an import-string target")
            assert target.application is not None
            return target.application
        assert target.import_string is not None
        if native.get("factory") is True:
            return target.import_string
        return load_application(target.import_string)

    def run(
        self,
        target: ServerTarget | object | None = None,
        config: ServerConfig | None = None,
    ) -> None:
        resolved = self._resolve_target(target)
        effective = config or self._default_config()
        native = self._validate_options(effective)
        application = self._resolve_for_run(resolved, effective, native)
        options: dict[str, Any] = {
            "host": effective.host,
            "port": effective.port,
            "workers": effective.workers,
            "reload": effective.reload,
            **native,
        }
        if effective.log_level is not None:
            options["log_level"] = effective.log_level
        uvicorn.run(cast(Any, application), **options)

    async def serve(
        self,
        target: ServerTarget | object | None = None,
        config: ServerConfig | None = None,
    ) -> None:
        resolved = self._resolve_target(target)
        effective = config or self._default_config()
        native = self._validate_options(effective)
        if effective.reload or effective.workers > 1:
            raise ServerConfigurationError(
                "Uvicorn async serve() supports one in-process worker without reload; "
                "use run() for process supervision."
            )
        application = self._resolve_for_async_serve(resolved, native)
        options: dict[str, Any] = {
            "host": effective.host,
            "port": effective.port,
            **native,
        }
        if effective.log_level is not None:
            options["log_level"] = effective.log_level
        server = uvicorn.Server(uvicorn.Config(cast(Any, application), **options))
        self._active_server = server
        try:
            await server.serve()
        finally:
            self._active_server = None

    def stop(self) -> None:
        if self._active_server is not None:
            self._active_server.should_exit = True
