import subprocess
from pathlib import Path

import pytest


@pytest.fixture(scope="session")
def all_package_distributions(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Build the immutable workspace distributions once for artifact consumers."""
    repository = Path(__file__).resolve().parents[2]
    output = tmp_path_factory.mktemp("all-package-distributions")
    subprocess.run(
        ["uv", "build", "--all-packages", "--out-dir", str(output)],
        cwd=repository,
        check=True,
        capture_output=True,
        text=True,
    )
    return output
