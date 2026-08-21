from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field

from .adapter_capabilities import (
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
from .capabilities import Capability, CapabilitySet


@dataclass(frozen=True, slots=True)
class CapabilityContract:
    capability: Capability
    version: int
    category: str
    prerequisites: CapabilitySet = field(default_factory=CapabilitySet)

    def __post_init__(self) -> None:
        if self.version < 1:
            raise ValueError("Capability contract version must be >= 1")
        if not self.category or self.category != self.category.strip():
            raise ValueError("Capability contract category must be a non-empty trimmed string")


CANONICAL_CAPABILITY_CONTRACTS: tuple[CapabilityContract, ...] = (
    CapabilityContract(WEB_ASGI, 1, "web"),
    CapabilityContract(WEB_HTTP_ROUTING, 1, "web"),
    CapabilityContract(WEB_STREAMING_RESPONSE, 1, "web"),
    CapabilityContract(SCHEMA_FIELD_INTROSPECTION, 1, "schema"),
    CapabilityContract(SCHEMA_INPUT_VALIDATION, 1, "schema"),
    CapabilityContract(SCHEMA_OUTPUT_SERIALIZATION, 1, "schema"),
    CapabilityContract(SCHEMA_PARTIAL_UPDATE, 1, "schema"),
    CapabilityContract(PERSISTENCE_READ, 1, "persistence"),
    CapabilityContract(PERSISTENCE_WRITE, 1, "persistence"),
    CapabilityContract(
        PERSISTENCE_RELATIONSHIPS,
        1,
        "persistence",
        CapabilitySet.of(PERSISTENCE_READ),
    ),
    CapabilityContract(TRANSACTIONS_ROOT_UOW, 1, "transactions"),
    CapabilityContract(
        CONCURRENCY_ATOMIC_OPTIMISTIC,
        1,
        "concurrency",
        CapabilitySet.of(PERSISTENCE_WRITE, TRANSACTIONS_ROOT_UOW),
    ),
)


def validate_capability_contracts(
    contracts: Iterable[CapabilityContract],
) -> tuple[CapabilityContract, ...]:
    contract_tuple = tuple(contracts)
    by_name: dict[str, CapabilityContract] = {}
    for contract in contract_tuple:
        name = contract.capability.name
        if name in by_name:
            raise ValueError(f'Duplicate canonical capability contract: "{name}"')
        by_name[name] = contract

    for contract in contract_tuple:
        name = contract.capability.name
        for prerequisite in contract.prerequisites.values:
            prerequisite_name = prerequisite.name
            if prerequisite_name == name:
                raise ValueError(f'Canonical capability "{name}" cannot require itself')
            if prerequisite_name not in by_name:
                raise ValueError(
                    f'Canonical capability "{name}" requires unknown capability '
                    f'"{prerequisite_name}"'
                )

    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(name: str, path: tuple[str, ...]) -> None:
        if name in visited:
            return
        if name in visiting:
            cycle_start = path.index(name)
            cycle = (*path[cycle_start:], name)
            raise ValueError("Canonical capability prerequisite cycle: " + " -> ".join(cycle))

        visiting.add(name)
        contract = by_name[name]
        for prerequisite_name in contract.prerequisites.names:
            visit(prerequisite_name, (*path, name))
        visiting.remove(name)
        visited.add(name)

    for name in sorted(by_name):
        visit(name, ())

    return contract_tuple


_VALIDATED_CANONICAL_CAPABILITY_CONTRACTS = validate_capability_contracts(
    CANONICAL_CAPABILITY_CONTRACTS
)
_CONTRACTS_BY_NAME = {
    contract.capability.name: contract for contract in _VALIDATED_CANONICAL_CAPABILITY_CONTRACTS
}


def get_capability_contract(
    capability: Capability | str,
) -> CapabilityContract | None:
    name = capability.name if isinstance(capability, Capability) else capability
    return _CONTRACTS_BY_NAME.get(name)


__all__ = [
    "CANONICAL_CAPABILITY_CONTRACTS",
    "CapabilityContract",
    "get_capability_contract",
    "validate_capability_contracts",
]