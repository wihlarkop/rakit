from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType

from .errors import ServerConfigurationError


@dataclass(frozen=True, slots=True)
class ServerConfig:
    host: str = "127.0.0.1"
    port: int = 8000
    workers: int = 1
    reload: bool = False
    log_level: str | None = None
    server_options: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.host or self.host != self.host.strip():
            raise ServerConfigurationError("Server host must be a non-empty trimmed string")
        if (
            not isinstance(self.port, int)
            or isinstance(self.port, bool)
            or not 1 <= self.port <= 65535
        ):
            raise ServerConfigurationError("Server port must be an integer between 1 and 65535")
        if not isinstance(self.workers, int) or isinstance(self.workers, bool) or self.workers < 1:
            raise ServerConfigurationError("Server workers must be a positive integer")
        if self.log_level is not None and (
            not isinstance(self.log_level, str)
            or not self.log_level
            or self.log_level != self.log_level.strip()
        ):
            raise ServerConfigurationError("Server log_level must be a non-empty trimmed string")

        native = dict(self.server_options)
        if any(not isinstance(name, str) or not name or name != name.strip() for name in native):
            raise ServerConfigurationError(
                "Every server option name must be a non-empty trimmed string"
            )
        object.__setattr__(self, "server_options", MappingProxyType(native))
