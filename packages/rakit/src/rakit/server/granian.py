from .._install import InstallExtra
from .._optional import OptionalDependency, optional_import

_DEPENDENCY = OptionalDependency(
    extra=InstallExtra.GRANIAN,
    label="Granian",
)

with optional_import("rakit_server_granian", dependency=_DEPENDENCY):
    import rakit_server_granian  # noqa: F401

from rakit_server_granian.server import GranianServer

__all__ = ["GranianServer"]
