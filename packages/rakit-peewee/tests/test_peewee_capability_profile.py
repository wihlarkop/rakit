from playhouse.pwasyncio import AsyncSqliteDatabase
from rakit_core.compiler import ApplicationBuilder
from rakit_core.conformance import advertised_canonical_capabilities
from rakit_core.testing.capability_conformance import CANONICAL_CONFORMANCE_SPEC_REGISTRY
from rakit_peewee.capabilities import PEEWEE_CAPABILITIES
from rakit_peewee.discovery import PEEWEE_INTEGRATION
from rakit_peewee.plugin import PeeweePlugin
from rakit_peewee.uow import PeeweeOperationUnitOfWorkFactory


def test_peewee_advertises_only_proven_capabilities() -> None:
    assert PEEWEE_CAPABILITIES.provider_id == "persistence.peewee"
    assert PEEWEE_CAPABILITIES.capabilities.names == (
        "persistence.read",
        "persistence.write",
        "transactions.root-uow",
    )
    assert "persistence.relationships" not in PEEWEE_CAPABILITIES.capabilities.names
    assert "concurrency.atomic-optimistic" not in PEEWEE_CAPABILITIES.capabilities.names


def test_peewee_discovery_matches_runtime_provider() -> None:
    assert PEEWEE_INTEGRATION.integration_id == PEEWEE_CAPABILITIES.provider_id
    assert PEEWEE_INTEGRATION.category == "persistence"
    assert PEEWEE_INTEGRATION.advertised_capabilities == PEEWEE_CAPABILITIES.capabilities


def test_peewee_advertised_capabilities_have_v1_conformance_specs() -> None:
    canonical = advertised_canonical_capabilities(PEEWEE_INTEGRATION)
    assert canonical == PEEWEE_CAPABILITIES.capabilities
    assert {
        (capability.name, 1) for capability in canonical.values
    } <= CANONICAL_CONFORMANCE_SPEC_REGISTRY.keys()


def test_peewee_plugin_records_configured_integration_and_uow_provider() -> None:
    database = AsyncSqliteDatabase(":memory:")
    builder = ApplicationBuilder()

    builder.install(PeeweePlugin(database=database))

    assert tuple(item.integration_id for item in builder.configured_integrations) == (
        "persistence.peewee",
    )
    factories = dict(builder.unit_of_work_factories)
    assert tuple(factories) == ("persistence.peewee",)
    assert isinstance(factories["persistence.peewee"], PeeweeOperationUnitOfWorkFactory)
