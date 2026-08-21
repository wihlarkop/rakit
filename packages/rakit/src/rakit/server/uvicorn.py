from .._install import InstallExtra
from .._optional import OptionalDependency, optional_import

# Guard a single-level import first: a dotted `from rakit_server_uvicorn.server
# import ...` raises ModuleNotFoundError(name="rakit_server_uvicorn.server") when
# the top-level package is missing, not name="rakit_server_uvicorn" -- which
# would slip past optional_import's narrow (exact module_name) safety check.
# Guarding the plain top-level import first gets the exception with the
# expected `.name`, then the real (unconditional, statically-typed) import
# below only runs once the package is confirmed present.
with optional_import(
    "rakit_server_uvicorn",
    dependency=OptionalDependency(
        extra=InstallExtra.UVICORN,
        label="Uvicorn",
    ),
):
    import rakit_server_uvicorn  # noqa: F401

from rakit_server_uvicorn.server import UvicornServer

__all__ = ["UvicornServer"]
