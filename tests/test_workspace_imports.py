from importlib.metadata import version
from types import ModuleType

import pytest
import rakit
import rakit_auth_sqlalchemy
import rakit_core
import rakit_server_uvicorn
import rakit_sqlalchemy
import rakit_storage
import rakit_storage_local
import rakit_web

OFFICIAL_PACKAGES: dict[str, tuple[str, ModuleType]] = {
    "rakit": ("rakit", rakit),
    "rakit-core": ("rakit_core", rakit_core),
    "rakit-web": ("rakit_web", rakit_web),
    "rakit-sqlalchemy": ("rakit_sqlalchemy", rakit_sqlalchemy),
    "rakit-auth-sqlalchemy": ("rakit_auth_sqlalchemy", rakit_auth_sqlalchemy),
    "rakit-storage": ("rakit_storage", rakit_storage),
    "rakit-storage-local": ("rakit_storage_local", rakit_storage_local),
    "rakit-server-uvicorn": ("rakit_server_uvicorn", rakit_server_uvicorn),
}


def test_official_packages_share_version() -> None:
    assert rakit.__version__ == "0.1.0a1"
    assert rakit_core.__version__ == "0.1.0a1"
    assert version("rakit") == version("rakit-core") == "0.1.0a1"


@pytest.mark.parametrize(
    ("distribution_name", "import_name", "module"),
    [(dist, import_name, module) for dist, (import_name, module) in OFFICIAL_PACKAGES.items()],
    ids=list(OFFICIAL_PACKAGES),
)
def test_all_official_packages_are_importable_and_at_release_version(
    distribution_name: str, import_name: str, module: ModuleType
) -> None:
    assert module.__version__ == "0.1.0a1"
    assert version(distribution_name) == "0.1.0a1"
