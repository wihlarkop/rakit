from dataclasses import dataclass
from typing import Protocol

from rakit_core.capabilities import CapabilitySet

from .config import ServerConfig
from .targets import ServerTarget


@dataclass(frozen=True, slots=True)
class ServerCapabilities:
    blocking_run: bool = True
    async_serve: bool = False
    graceful_stop: bool = False
    reload: bool = False
    workers: bool = False
    app_object: bool = True
    import_string: bool = True

    def __post_init__(self) -> None:
        if not self.blocking_run:
            raise ValueError("Every Rakit server adapter must support blocking run")

    @property
    def capability_set(self) -> CapabilitySet:
        names = ["server.blocking-run"]
        if self.async_serve:
            names.append("server.async-serve")
        if self.graceful_stop:
            names.append("server.graceful-stop")
        if self.reload:
            names.append("server.reload")
        if self.workers:
            names.append("server.workers")
        if self.app_object:
            names.append("server.target.object")
        if self.import_string:
            names.append("server.target.import-string")
        return CapabilitySet.of(*names)


class ServerAdapter(Protocol):
    name: str
    capabilities: ServerCapabilities

    def run(self, target: ServerTarget, config: ServerConfig) -> None: ...
