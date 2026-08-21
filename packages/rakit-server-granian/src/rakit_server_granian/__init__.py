from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .server import GranianServer as GranianServer

__version__ = "0.1.0a1"

__all__ = ["GranianServer", "__version__"]


def __getattr__(name: str) -> object:
    if name == "GranianServer":
        from .server import GranianServer

        return GranianServer
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
