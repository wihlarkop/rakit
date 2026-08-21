from .._install import InstallExtra
from .._optional import OptionalDependency, optional_import

with optional_import(
    "rakit_server_granian",
    dependency=OptionalDependency(
        extra=InstallExtra.GRANIAN,
        label="Granian",
    ),
):
    import rakit_server_granian  # noqa: F401

from rakit_server_granian.server import GranianServer

__all__ = ["GranianServer"]
