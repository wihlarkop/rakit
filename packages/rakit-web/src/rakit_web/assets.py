"""Bundled, content-addressed assets for the built-in read-only UI."""

from dataclasses import dataclass
from hashlib import sha256
from importlib.resources import files
from pathlib import PurePosixPath

from starlette.exceptions import HTTPException
from starlette.responses import Response
from starlette.staticfiles import StaticFiles
from starlette.types import Scope

_CACHE_CONTROL = "public, max-age=31536000, immutable"
_STATIC_DIRECTORY = files("rakit_web").joinpath("static")


@dataclass(frozen=True)
class _Asset:
    source_name: str
    hashed_name: str


def _asset(source_name: str) -> _Asset:
    content = _STATIC_DIRECTORY.joinpath(source_name).read_bytes()
    digest = sha256(content).hexdigest()[:8]
    path = PurePosixPath(source_name)
    hashed_name = f"{path.stem}.{digest}{path.suffix}"
    return _Asset(source_name=source_name, hashed_name=hashed_name)


_ASSETS = {
    name: _asset(name)
    for name in (
        "rakit.css",
        "rakit-ui.js",
        "rakit-widgets.js",
        "rakit-shell.js",
        "htmx.min.js",
        "theme.js",
    )
}
_HASHED_ASSETS = {asset.hashed_name: asset for asset in _ASSETS.values()}


def static_url(name: str) -> str:
    """Return the immutable local URL for a known logical asset name."""

    try:
        asset = _ASSETS[name]
    except KeyError:
        raise KeyError(f"Unknown bundled asset: {name!r}") from None
    return f"/_system/static/{asset.hashed_name}"


class ImmutableStaticFiles(StaticFiles):
    """Serve only the known content-hashed aliases for bundled assets."""

    def __init__(self) -> None:
        super().__init__(directory=str(_STATIC_DIRECTORY), check_dir=True)

    async def get_response(self, path: str, scope: Scope) -> Response:
        asset = _HASHED_ASSETS.get(path)
        if asset is None:
            raise HTTPException(status_code=404)
        response = await super().get_response(asset.source_name, scope)
        response.headers["Cache-Control"] = _CACHE_CONTROL
        return response


def static_files() -> StaticFiles:
    """Build the ASGI application mounted at ``/_system/static``."""

    return ImmutableStaticFiles()


__all__ = ["static_url"]
