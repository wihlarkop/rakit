from collections.abc import Mapping

from rakit_server import ServerAdapterNotFoundError
from rakit_server import run as _run_server

from ._install import InstallExtra, format_uv_add_command

_SERVER_EXTRAS = {
    "uvicorn": InstallExtra.UVICORN,
    "granian": InstallExtra.GRANIAN,
}


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
) -> None:
    """Serve a Rakit Admin, raw ASGI callable, or import-string target."""
    try:
        _run_server(
            target,
            server=server,
            host=host,
            port=port,
            workers=workers,
            reload=reload,
            log_level=log_level,
            server_options=server_options,
        )
    except ServerAdapterNotFoundError as exc:
        extra = _SERVER_EXTRAS.get(server)
        if extra is None:
            raise
        hint = format_uv_add_command(extra)
        raise ServerAdapterNotFoundError(f"{exc}. Install it with: {hint}") from exc
