from rakit_core.compiler import ApplicationBuilder
from rakit_core.conformance import advertised_canonical_capabilities
from rakit_core.testing.capability_conformance import CANONICAL_CONFORMANCE_SPEC_REGISTRY
from rakit_tortoise.capabilities import TORTOISE_CAPABILITIES
from rakit_tortoise.discovery import TORTOISE_INTEGRATION
from rakit_tortoise.plugin import TortoisePlugin
from rakit_tortoise.uow import TortoiseOperationUnitOfWorkFactory


def test_tortoise_advertises_only_proven_capabilities() -> None:
    assert TORTOISE_CAPABILITIES.provider_id == "persistence.tortoise"
    assert TORTOISE_CAPABILITIES.capabilities.names == (
        "persistence.read",
        "persistence.write",
        "transactions.root-uow",
    )
    assert "persistence.relationships" not in TORTOISE_CAPABILITIES.capabilities.names
    assert "concurrency.atomic-optimistic" not in TORTOISE_CAPABILITIES.capabilities.names


def test_tortoise_discovery_matches_runtime_provider() -> None:
    assert TORTOISE_INTEGRATION.integration_id == "persistence.tortoise"
    assert TORTOISE_INTEGRATION.category == "persistence"
    assert TORTOISE_INTEGRATION.advertised_capabilities == TORTOISE_CAPABILITIES.capabilities


def test_tortoise_advertised_capabilities_have_v1_conformance_specs() -> None:
    canonical = advertised_canonical_capabilities(TORTOISE_INTEGRATION)
    assert canonical == TORTOISE_CAPABILITIES.capabilities
    assert {
        (capability.name, 1) for capability in canonical.values
    } <= CANONICAL_CONFORMANCE_SPEC_REGISTRY.keys()


def test_tortoise_plugin_records_configured_integration_and_uow_provider() -> None:
    builder = ApplicationBuilder()

    builder.install(TortoisePlugin())

    assert tuple(item.integration_id for item in builder.configured_integrations) == (
        "persistence.tortoise",
    )
    factories = dict(builder.unit_of_work_factories)
    assert tuple(factories) == ("persistence.tortoise",)
    assert isinstance(factories["persistence.tortoise"], TortoiseOperationUnitOfWorkFactory)
