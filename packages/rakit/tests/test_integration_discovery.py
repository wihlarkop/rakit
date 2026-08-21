import subprocess
import sys
from importlib.metadata import EntryPoint

import pytest
from rakit._integration_discovery import (
    InstalledIntegrationDiscoveryError,
    discover_installed_integrations,
)


def test_first_party_installed_integrations_are_discovered_without_activation() -> None:
    discovered = discover_installed_integrations()

    assert tuple(item.integration_id for item in discovered) == (
        "auth.sqlalchemy",
        "persistence.sqlalchemy",
        "schema.msgspec",
        "schema.pydantic",
        "server.granian",
        "server.uvicorn",
        "storage.local",
        "web.starlette",
    )
    assert {item.category for item in discovered} == {
        "authentication",
        "persistence",
        "schema",
        "server",
        "storage",
        "web",
    }


def test_server_discovery_modules_do_not_import_runtime_servers() -> None:
    checks = (
        ("rakit_server_uvicorn.discovery", "uvicorn"),
        ("rakit_server_granian.discovery", "granian"),
    )
    for discovery_module, runtime_module in checks:
        result = subprocess.run(
            [
                sys.executable,
                "-c",
                (
                    "import sys; "
                    f"import {discovery_module}; "
                    f'assert "{runtime_module}" not in sys.modules'
                ),
            ],
            check=False,
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, result.stderr


def test_installed_discovery_rejects_wrong_descriptor_type() -> None:
    candidate = EntryPoint(
        name="bad.type",
        value="builtins:object",
        group="rakit.integrations",
    )

    with pytest.raises(InstalledIntegrationDiscoveryError, match="IntegrationDescriptor"):
        discover_installed_integrations(candidates=(candidate,))


def test_installed_discovery_rejects_entry_point_name_mismatch() -> None:
    candidate = EntryPoint(
        name="wrong.name",
        value="rakit_web.discovery:STARLETTE_INTEGRATION",
        group="rakit.integrations",
    )

    with pytest.raises(InstalledIntegrationDiscoveryError, match="does not match descriptor id"):
        discover_installed_integrations(candidates=(candidate,))


def test_installed_discovery_rejects_duplicate_ids() -> None:
    candidate = EntryPoint(
        name="web.starlette",
        value="rakit_web.discovery:STARLETTE_INTEGRATION",
        group="rakit.integrations",
    )

    with pytest.raises(
        InstalledIntegrationDiscoveryError, match="Duplicate installed integration id"
    ):
        discover_installed_integrations(candidates=(candidate, candidate))
