from typing import Mapping

from .config import ServerConfig
from .registry import ServerRegistry
from .targets import resolve_server_target


def run(
    target: object,
    *,
    server: str = "uvicorn",
    host: str = "127.0.0.1",
    port: int = 8000,
    workers: int = 1,
    reload: bool = False,
    log_level: str | None = None,
    server_options: Mapping[str, object] | None = None,
    registry: ServerRegistry | None = None,
) -> None:
    selected_registry = registry or ServerRegistry()
    adapter = selected_registry.create(server)
    resolved_target = resolve_server_target(target)
    config = ServerConfig(
        host=host,
        port=port,
        workers=workers,
        reload=reload,
        log_level=log_level,
        server_options={} if server_options is None else server_options,
    )
    adapter.run(resolved_target, config)
