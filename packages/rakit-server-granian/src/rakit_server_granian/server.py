import sys
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, ClassVar

from granian import Granian
from granian.constants import Interfaces
from granian.log import LogLevels
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

_RESERVED_OPTIONS = {
    "target",
    "address",
    "port",
    "interface",
    "workers",
    "reload",
    "log_level",
    "factory",
}


def _load_granian_target(spec: str) -> ASGIApplication:
    """Load Rakit Admin objects or raw ASGI targets inside each Granian worker."""
    return load_application(spec)


@dataclass(slots=True)
class GranianServer:
    host: str = "127.0.0.1"
    port: int = 8000
    workers: int = 1
    reload: bool = False
    log_level: str | None = None
    server_options: Mapping[str, object] = field(default_factory=dict)

    name: ClassVar[str] = "granian"
    capabilities: ClassVar[ServerCapabilities] = ServerCapabilities(
        reload=True,
        workers=True,
        app_object=False,
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

    @staticmethod
    def _validate_options(config: ServerConfig) -> tuple[dict[str, object], LogLevels]:
        native = dict(config.server_options)
        conflicts = sorted(_RESERVED_OPTIONS.intersection(native))
        if conflicts:
            raise ServerConfigurationError(
                "Granian server_options cannot override portable option(s): "
                + ", ".join(conflicts)
            )
        if sys.platform == "win32" and config.workers > 1:
            raise ServerConfigurationError(
                "Granian does not support multiple process workers on Windows; use workers=1"
            )
        try:
            level = LogLevels(config.log_level or "info")
        except ValueError as exc:
            raise ServerConfigurationError(
                f'Unsupported Granian log level "{config.log_level}"'
            ) from exc
        return native, level

    def run(self, target: ServerTarget | object, config: ServerConfig | None = None) -> None:
        resolved = target if isinstance(target, ServerTarget) else resolve_server_target(target)
        effective = config or self._default_config()
        native, log_level = self._validate_options(effective)
        if resolved.kind is not ServerTargetKind.IMPORT_STRING or resolved.import_string is None:
            raise ServerConfigurationError(
                "Granian's standard process server requires an import-string target. "
                "Use GranianServer().run(\"module:admin\") or "
                "rakit.run(\"module:admin\", server=\"granian\")."
            )

        options: dict[str, Any] = {
            "target": resolved.import_string,
            "address": effective.host,
            "port": effective.port,
            "interface": Interfaces.ASGI,
            "workers": effective.workers,
            "reload": effective.reload,
            "log_level": log_level,
            **native,
        }
        server = Granian(**options)
        server.serve(target_loader=_load_granian_target)
