from rakit_core.compiler import ApplicationBuilder
from rakit_core.conformance import advertised_canonical_capabilities
from rakit_core.testing.capability_conformance import CANONICAL_CONFORMANCE_SPEC_REGISTRY
from rakit_sqlalchemy.capabilities import SQLALCHEMY_CAPABILITIES
from rakit_sqlalchemy.discovery import SQLALCHEMY_INTEGRATION
from rakit_sqlalchemy.plugin import SQLAlchemyPlugin
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine


def test_sqlalchemy_declares_persistence_transaction_and_concurrency_capabilities() -> None:
    assert SQLALCHEMY_CAPABILITIES.provider_id == "persistence.sqlalchemy"
    assert SQLALCHEMY_CAPABILITIES.capabilities.names == (
        "concurrency.atomic-optimistic",
        "persistence.read",
        "persistence.relationships",
        "persistence.write",
        "transactions.root-uow",
    )


def test_sqlalchemy_discovery_descriptor_matches_runtime_capability_provider() -> None:
    assert SQLALCHEMY_INTEGRATION.integration_id == "persistence.sqlalchemy"
    assert SQLALCHEMY_INTEGRATION.category == "persistence"
    assert SQLALCHEMY_INTEGRATION.advertised_capabilities == SQLALCHEMY_CAPABILITIES.capabilities


def test_sqlalchemy_advertised_capabilities_all_have_v1_conformance_specs() -> None:
    canonical = advertised_canonical_capabilities(SQLALCHEMY_INTEGRATION)
    assert canonical == SQLALCHEMY_CAPABILITIES.capabilities
    assert {
        (capability.name, 1) for capability in canonical.values
    } <= CANONICAL_CONFORMANCE_SPEC_REGISTRY.keys()


def test_sqlalchemy_plugin_records_configured_integration() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    builder = ApplicationBuilder()

    builder.install(SQLAlchemyPlugin(session_factory=session_factory))

    assert tuple(item.integration_id for item in builder.configured_integrations) == (
        "persistence.sqlalchemy",
    )
