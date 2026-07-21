from importlib import metadata

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


def test_all_installed_same_version_succeeds(monkeypatch: pytest.MonkeyPatch) -> None:
    versions = {"rakit": "0.1.0a1", "rakit-core": "0.1.0a1"}
    monkeypatch.setattr(
        "rakit_core.compatibility.metadata.version",
        lambda name: versions[name],
    )
    result = validate_official_package_versions(("rakit", "rakit-core"))
    assert result == "0.1.0a1"


def test_missing_optional_packages_are_skipped(monkeypatch: pytest.MonkeyPatch) -> None:
    versions = {"rakit": "0.1.0a1", "rakit-core": "0.1.0a1"}
    missing = {"rakit-sqlalchemy", "rakit-storage"}

    def fake_version(name: str) -> str:
        if name in missing:
            raise metadata.PackageNotFoundError(name)
        return versions[name]

    monkeypatch.setattr("rakit_core.compatibility.metadata.version", fake_version)
    result = validate_official_package_versions(
        ("rakit", "rakit-core", "rakit-sqlalchemy", "rakit-storage")
    )
    assert result == "0.1.0a1"


def test_missing_packages_do_not_mask_real_mismatch(monkeypatch: pytest.MonkeyPatch) -> None:
    versions = {"rakit": "0.1.0a1", "rakit-core": "0.2.0a1"}
    missing = {"rakit-sqlalchemy"}

    def fake_version(name: str) -> str:
        if name in missing:
            raise metadata.PackageNotFoundError(name)
        return versions[name]

    monkeypatch.setattr("rakit_core.compatibility.metadata.version", fake_version)
    with pytest.raises(RakitError) as caught:
        validate_official_package_versions(("rakit", "rakit-core", "rakit-sqlalchemy"))
    assert caught.value.code == "config.package_version_mismatch"
