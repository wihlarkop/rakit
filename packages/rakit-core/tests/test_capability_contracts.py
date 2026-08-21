from __future__ import annotations

import pytest
from rakit_core.adapter_capabilities import (
    CONCURRENCY_ATOMIC_OPTIMISTIC,
    PERSISTENCE_READ,
    PERSISTENCE_RELATIONSHIPS,
    PERSISTENCE_WRITE,
    SCHEMA_FIELD_INTROSPECTION,
    SCHEMA_INPUT_VALIDATION,
    SCHEMA_OUTPUT_SERIALIZATION,
    SCHEMA_PARTIAL_UPDATE,
    TRANSACTIONS_ROOT_UOW,
    WEB_ASGI,
    WEB_HTTP_ROUTING,
    WEB_STREAMING_RESPONSE,
)
from rakit_core.capabilities import Capability, CapabilitySet
from rakit_core.capability_contracts import (
    CANONICAL_CAPABILITY_CONTRACTS,
    CapabilityContract,
    get_capability_contract,
    validate_capability_contracts,
)


EXPECTED_CANONICAL_NAMES = {
    WEB_ASGI.name,
    WEB_HTTP_ROUTING.name,
    WEB_STREAMING_RESPONSE.name,
    SCHEMA_FIELD_INTROSPECTION.name,
    SCHEMA_INPUT_VALIDATION.name,
    SCHEMA_OUTPUT_SERIALIZATION.name,
    SCHEMA_PARTIAL_UPDATE.name,
    PERSISTENCE_READ.name,
    PERSISTENCE_WRITE.name,
    PERSISTENCE_RELATIONSHIPS.name,
    TRANSACTIONS_ROOT_UOW.name,
    CONCURRENCY_ATOMIC_OPTIMISTIC.name,
}


def test_canonical_registry_covers_exact_v1_vocabulary() -> None:
    assert {contract.capability.name for contract in CANONICAL_CAPABILITY_CONTRACTS} == (
        EXPECTED_CANONICAL_NAMES
    )
    assert all(contract.version == 1 for contract in CANONICAL_CAPABILITY_CONTRACTS)
    assert get_capability_contract("vendor.custom") is None


def test_relationships_and_optimistic_concurrency_have_semantic_prerequisites() -> None:
    relationships = get_capability_contract(PERSISTENCE_RELATIONSHIPS)
    concurrency = get_capability_contract(CONCURRENCY_ATOMIC_OPTIMISTIC)
    assert relationships is not None
    assert relationships.prerequisites.names == (PERSISTENCE_READ.name,)
    assert concurrency is not None
    assert set(concurrency.prerequisites.names) == {
        PERSISTENCE_WRITE.name,
        TRANSACTIONS_ROOT_UOW.name,
    }


def test_duplicate_contract_is_rejected() -> None:
    contract = CapabilityContract(Capability("test.one"), 1, "test")
    with pytest.raises(ValueError, match="Duplicate canonical capability contract"):
        validate_capability_contracts((contract, contract))


def test_unknown_prerequisite_is_rejected() -> None:
    contract = CapabilityContract(
        Capability("test.one"),
        1,
        "test",
        CapabilitySet.of(Capability("test.missing")),
    )
    with pytest.raises(ValueError, match="requires unknown capability"):
        validate_capability_contracts((contract,))


def test_self_prerequisite_is_rejected() -> None:
    capability = Capability("test.self")
    contract = CapabilityContract(capability, 1, "test", CapabilitySet.of(capability))
    with pytest.raises(ValueError, match="cannot require itself"):
        validate_capability_contracts((contract,))


def test_prerequisite_cycle_is_rejected_deterministically() -> None:
    first = Capability("test.first")
    second = Capability("test.second")
    contracts = (
        CapabilityContract(first, 1, "test", CapabilitySet.of(second)),
        CapabilityContract(second, 1, "test", CapabilitySet.of(first)),
    )
    with pytest.raises(ValueError, match=r"test\.first -> test\.second -> test\.first"):
        validate_capability_contracts(contracts)


def test_invalid_contract_version_and_category_are_rejected() -> None:
    with pytest.raises(ValueError, match="version must be >= 1"):
        CapabilityContract(Capability("test.zero"), 0, "test")
    with pytest.raises(ValueError, match="category must be a non-empty trimmed string"):
        CapabilityContract(Capability("test.category"), 1, " test ")
