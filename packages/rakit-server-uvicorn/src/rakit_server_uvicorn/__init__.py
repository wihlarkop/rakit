from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .server import UvicornServer as UvicornServer

__version__ = "0.1.0a1"

__all__ = ["UvicornServer", "__version__"]


def __getattr__(name: str) -> object:
    if name == "UvicornServer":
        from .server import UvicornServer

        return UvicornServer
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
