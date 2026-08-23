from piccolo.engine.sqlite import SQLiteEngine
from rakit_core.compiler import ApplicationBuilder
from rakit_core.conformance import advertised_canonical_capabilities
from rakit_core.testing.capability_conformance import CANONICAL_CONFORMANCE_SPEC_REGISTRY
from rakit_piccolo.capabilities import PICCOLO_CAPABILITIES
from rakit_piccolo.discovery import PICCOLO_INTEGRATION
from rakit_piccolo.plugin import PiccoloPlugin
from rakit_piccolo.uow import PiccoloOperationUnitOfWorkFactory


def test_piccolo_advertises_only_proven_capabilities() -> None:
    assert PICCOLO_CAPABILITIES.provider_id == "persistence.piccolo"
    assert PICCOLO_CAPABILITIES.capabilities.names == (
        "persistence.read",
        "persistence.write",
        "transactions.root-uow",
    )
    assert "persistence.relationships" not in PICCOLO_CAPABILITIES.capabilities.names
    assert "concurrency.atomic-optimistic" not in PICCOLO_CAPABILITIES.capabilities.names


def test_piccolo_discovery_matches_runtime_provider() -> None:
    assert PICCOLO_INTEGRATION.integration_id == PICCOLO_CAPABILITIES.provider_id
    assert PICCOLO_INTEGRATION.category == "persistence"
    assert PICCOLO_INTEGRATION.advertised_capabilities == PICCOLO_CAPABILITIES.capabilities


def test_piccolo_advertised_capabilities_have_v1_conformance_specs() -> None:
    canonical = advertised_canonical_capabilities(PICCOLO_INTEGRATION)
    assert canonical == PICCOLO_CAPABILITIES.capabilities
    assert {
        (capability.name, 1) for capability in canonical.values
    } <= CANONICAL_CONFORMANCE_SPEC_REGISTRY.keys()


def test_piccolo_plugin_records_configured_integration_and_uow_provider(tmp_path) -> None:
    engine = SQLiteEngine(path=str(tmp_path / "piccolo-profile.sqlite3"))
    builder = ApplicationBuilder()

    builder.install(PiccoloPlugin(engine=engine))

    assert tuple(item.integration_id for item in builder.configured_integrations) == (
        "persistence.piccolo",
    )
    factories = dict(builder.unit_of_work_factories)
    assert tuple(factories) == ("persistence.piccolo",)
    assert isinstance(factories["persistence.piccolo"], PiccoloOperationUnitOfWorkFactory)
