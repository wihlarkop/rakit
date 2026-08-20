from .._optional import optional_import

with optional_import("rakit_server_granian", extra="granian"):
    import rakit_server_granian  # noqa: F401

from rakit_server_granian.server import GranianServer

__all__ = ["GranianServer"]
