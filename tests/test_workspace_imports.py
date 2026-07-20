from importlib.metadata import version

import rakit
import rakit_core


def test_official_packages_share_version() -> None:
    assert rakit.__version__ == "0.1.0a1"
    assert rakit_core.__version__ == "0.1.0a1"
    assert version("rakit") == version("rakit-core") == "0.1.0a1"
