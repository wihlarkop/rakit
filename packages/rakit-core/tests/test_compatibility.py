import pytest
from rakit_core.compatibility import validate_official_package_versions
from rakit_core.errors import RakitError


def test_mixed_versions_fail(monkeypatch: pytest.MonkeyPatch) -> None:
    versions = {"rakit": "0.1.0a1", "rakit-core": "0.2.0a1"}
    monkeypatch.setattr(
        "rakit_core.compatibility.metadata.version",
        lambda name: versions[name],
    )
    with pytest.raises(RakitError) as caught:
        validate_official_package_versions(("rakit", "rakit-core"))
    assert caught.value.code == "config.package_version_mismatch"
