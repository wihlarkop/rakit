import pytest
import rakit_core.adapter_capabilities as adapter_capabilities
import rakit_core.capability_contracts as capability_contracts
from rakit_core.capabilities import Capability, CapabilitySet


EXPECTED_CANONICAL_NAMES = {
    adapter_capabilities.WEB_ASGI.name,
    adapter_capabilities.WEB_HTTP_ROUTING.name,
    adapter_capabilities.WEB_STREAMING_RESPONSE.name,
    adapter_capabilities.SCHEMA_FIELD_INTROSPECTION.name,
    adapter_capabilities.SCHEMA_INPUT_VALIDATION.name,
    adapter_capabilities.SCHEMA_OUTPUT_SERIALIZATION.name,
    adapter_capabilities.SCHEMA_PARTIAL_UPDATE.name,
    adapter_capabilities.PERSISTENCE_READ.name,
    adapter_capabilities.PERSISTENCE_WRITE.name,
    adapter_capabilities.PERSISTENCE_RELATIONSHIPS.name,
    adapter_capabilities.TRANSACTIONS_ROOT_UOW.name,
    adapter_capabilities.CONCURRENCY_ATOMIC_OPTIMISTIC.name,
}


def test_canonical_registry_covers_exact_v1_vocabulary() -> None:
    contracts = capability_contracts.CANONICAL_CAPABILITY_CONTRACTS
    names = {contract.capability.name for contract in contracts}
    assert names == EXPECTED_CANONICAL_NAMES
    assert all(contract.version == 1 for contract in contracts)
    assert capability_contracts.get_capability_contract("vendor.custom") is None


def test_relationships_and_optimistic_concurrency_have_semantic_prerequisites() -> None:
    relationships = capability_contracts.get_capability_contract(
        adapter_capabilities.PERSISTENCE_RELATIONSHIPS
    )
    concurrency = capability_contracts.get_capability_contract(
        adapter_capabilities.CONCURRENCY_ATOMIC_OPTIMISTIC
    )
    assert relationships is not None
    assert relationships.prerequisites.names == (adapter_capabilities.PERSISTENCE_READ.name,)
    assert concurrency is not None
    assert set(concurrency.prerequisites.names) == {
        adapter_capabilities.PERSISTENCE_WRITE.name,
        adapter_capabilities.TRANSACTIONS_ROOT_UOW.name,
    }


def test_duplicate_contract_is_rejected() -> None:
    contract = capability_contracts.CapabilityContract(Capability("test.one"), 1, "test")
    with pytest.raises(ValueError, match="Duplicate canonical capability contract"):
        capability_contracts.validate_capability_contracts((contract, contract))


def test_unknown_prerequisite_is_rejected() -> None:
    contract = capability_contracts.CapabilityContract(
        Capability("test.one"),
        1,
        "test",
        CapabilitySet.of(Capability("test.missing")),
    )
    with pytest.raises(ValueError, match="requires unknown capability"):
        capability_contracts.validate_capability_contracts((contract,))


def test_self_prerequisite_is_rejected() -> None:
    capability = Capability("test.self")
    contract = capability_contracts.CapabilityContract(
        capability, 1, "test", CapabilitySet.of(capability)
    )
    with pytest.raises(ValueError, match="cannot require itself"):
        capability_contracts.validate_capability_contracts((contract,))


def test_prerequisite_cycle_is_rejected_deterministically() -> None:
    first = Capability("test.first")
    second = Capability("test.second")
    contracts = (
        capability_contracts.CapabilityContract(first, 1, "test", CapabilitySet.of(second)),
        capability_contracts.CapabilityContract(second, 1, "test", CapabilitySet.of(first)),
    )
    with pytest.raises(ValueError, match=r"test\.first -> test\.second -> test\.first"):
        capability_contracts.validate_capability_contracts(contracts)


def test_invalid_contract_version_and_category_are_rejected() -> None:
    with pytest.raises(ValueError, match="version must be >= 1"):
        capability_contracts.CapabilityContract(Capability("test.zero"), 0, "test")
    with pytest.raises(ValueError, match="category must be a non-empty trimmed string"):
        capability_contracts.CapabilityContract(Capability("test.category"), 1, " test ")
