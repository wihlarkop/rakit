from __future__ import annotations

import tomllib
from pathlib import Path

from rakit._integration_discovery import discover_installed_integrations
from rakit_peewee.capabilities import PEEWEE_CAPABILITIES
from rakit_piccolo.capabilities import PICCOLO_CAPABILITIES
from rakit_sqlalchemy.capabilities import SQLALCHEMY_CAPABILITIES, SQLALCHEMY_CORE_CAPABILITIES
from rakit_tortoise.capabilities import TORTOISE_CAPABILITIES

_REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
_RAKIT_PYPROJECT = _REPOSITORY_ROOT / "packages" / "rakit" / "pyproject.toml"
_PERSISTENCE_GUIDE = _REPOSITORY_ROOT / "docs" / "guides" / "persistence-adapters.md"

_EXPECTED_CAPABILITIES = {
    "persistence.sqlalchemy": (
        "concurrency.atomic-optimistic",
        "persistence.read",
        "persistence.relationships",
        "persistence.write",
        "transactions.root-uow",
    ),
    "persistence.sqlalchemy-core": (
        "persistence.read",
        "persistence.write",
        "transactions.root-uow",
    ),
    "persistence.tortoise": (
        "persistence.read",
        "persistence.write",
        "transactions.root-uow",
    ),
    "persistence.peewee": (
        "persistence.read",
        "persistence.write",
        "transactions.root-uow",
    ),
    "persistence.piccolo": (
        "persistence.read",
        "persistence.write",
        "transactions.root-uow",
    ),
}

_EXPECTED_EXTRAS = {
    "sqlalchemy": ["rakit-sqlalchemy==0.1.0a1"],
    "tortoise": ["rakit-tortoise==0.1.0a1"],
    "peewee": ["rakit-peewee==0.1.0a1"],
    "piccolo": ["rakit-piccolo==0.1.0a1"],
}

_EXPECTED_UPSTREAM_RANGES = (
    "sqlalchemy[asyncio]>=2.0.16,<2.1",
    "tortoise-orm>=1.1.7,<2",
    "peewee>=4.0.2,<5",
    "piccolo>=1.30,<2",
)


def test_persistence_capability_matrix_matches_shipped_providers() -> None:
    providers = (
        SQLALCHEMY_CAPABILITIES,
        SQLALCHEMY_CORE_CAPABILITIES,
        TORTOISE_CAPABILITIES,
        PEEWEE_CAPABILITIES,
        PICCOLO_CAPABILITIES,
    )

    assert {provider.provider_id: provider.capabilities.names for provider in providers} == (
        _EXPECTED_CAPABILITIES
    )


def test_persistence_extras_are_explicit_and_standard_stays_sqlalchemy_only() -> None:
    project = tomllib.loads(_RAKIT_PYPROJECT.read_text(encoding="utf-8"))["project"]
    optional = project["optional-dependencies"]

    for extra, requirements in _EXPECTED_EXTRAS.items():
        assert optional[extra] == requirements

    assert optional["standard"] == [
        "rakit-sqlalchemy==0.1.0a1",
        "rakit-auth-sqlalchemy==0.1.0a1",
        "rakit-storage-local==0.1.0a1",
    ]
    assert "masonite" not in optional
    assert "masonite-orm" not in optional


def test_all_shipped_persistence_integrations_coexist_in_discovery() -> None:
    discovered = discover_installed_integrations()
    persistence = tuple(
        item.integration_id for item in discovered if item.category == "persistence"
    )

    assert persistence == tuple(sorted(_EXPECTED_CAPABILITIES))
    assert "persistence.masonite" not in persistence


def test_persistence_guide_tracks_provider_ids_ranges_and_deferred_masonite() -> None:
    guide = _PERSISTENCE_GUIDE.read_text(encoding="utf-8")

    for provider_id in _EXPECTED_CAPABILITIES:
        assert f"`{provider_id}`" in guide
    for dependency_range in _EXPECTED_UPSTREAM_RANGES:
        assert f"`{dependency_range}`" in guide

    assert "Masonite ORM remains a **Research** item." in guide
    assert "does not currently ship `persistence.masonite`" in guide
