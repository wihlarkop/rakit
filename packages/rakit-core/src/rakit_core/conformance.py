from __future__ import annotations

from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass
from enum import StrEnum

from .capabilities import Capability, CapabilitySet
from .capability_contracts import (
    CapabilityContract,
    get_capability_contract,
)
from .integrations import IntegrationDescriptor


class ConformanceFailureKind(StrEnum):
    REGISTRY = "registry"
    ADVERTISEMENT = "advertisement"
    BEHAVIOR = "behavior"


@dataclass(frozen=True, slots=True)
class ConformanceFailure:
    kind: ConformanceFailureKind
    message: str
    capability: str | None = None
    check_id: str | None = None

    def __post_init__(self) -> None:
        if not self.message or self.message != self.message.strip():
            raise ValueError("Conformance failure message must be a non-empty trimmed string")


@dataclass(frozen=True, slots=True)
class CapabilityConformanceResult:
    capability: str
    contract_version: int
    failures: tuple[ConformanceFailure, ...] = ()

    @property
    def passed(self) -> bool:
        return not self.failures


@dataclass(frozen=True, slots=True)
class IntegrationConformanceResult:
    integration_id: str
    results: tuple[CapabilityConformanceResult, ...]

    @property
    def passed(self) -> bool:
        return all(result.passed for result in self.results)

    @property
    def failures(self) -> tuple[ConformanceFailure, ...]:
        return tuple(failure for result in self.results for failure in result.failures)


CapabilityCheckCallable = Callable[[object], Awaitable[None]]


@dataclass(frozen=True, slots=True)
class CapabilityBehaviorCheck:
    check_id: str
    run: CapabilityCheckCallable

    def __post_init__(self) -> None:
        if not self.check_id or self.check_id != self.check_id.strip():
            raise ValueError("Capability check id must be a non-empty trimmed string")


@dataclass(frozen=True, slots=True)
class CapabilityConformanceSpec:
    capability: Capability
    version: int
    checks: tuple[CapabilityBehaviorCheck, ...]

    def __post_init__(self) -> None:
        if self.version < 1:
            raise ValueError("Capability conformance spec version must be >= 1")
        seen: set[str] = set()
        for check in self.checks:
            if check.check_id in seen:
                raise ValueError(f'Duplicate conformance check id: "{check.check_id}"')
            seen.add(check.check_id)


def validate_advertised_capabilities(
    descriptor: IntegrationDescriptor,
) -> tuple[ConformanceFailure, ...]:
    advertised = descriptor.advertised_capabilities
    failures: list[ConformanceFailure] = []

    for capability_name in advertised.names:
        contract = get_capability_contract(capability_name)
        if contract is None:
            continue
        missing = contract.prerequisites.difference(advertised)
        if not missing.values:
            continue
        failures.append(
            ConformanceFailure(
                kind=ConformanceFailureKind.ADVERTISEMENT,
                capability=capability_name,
                message=(
                    f'Integration "{descriptor.integration_id}" advertises canonical '
                    f'capability "{capability_name}" without prerequisites: '
                    + ", ".join(missing.names)
                ),
            )
        )

    return tuple(failures)


def _spec_key(capability: Capability | str, version: int) -> tuple[str, int]:
    name = capability.name if isinstance(capability, Capability) else capability
    return name, version


def build_conformance_spec_registry(
    specs: Iterable[CapabilityConformanceSpec],
) -> dict[tuple[str, int], CapabilityConformanceSpec]:
    registry: dict[tuple[str, int], CapabilityConformanceSpec] = {}
    for spec in specs:
        key = _spec_key(spec.capability, spec.version)
        if key in registry:
            raise ValueError(f'Duplicate conformance spec for capability "{key[0]}" v{key[1]}')
        contract = get_capability_contract(spec.capability)
        if contract is None:
            raise ValueError(
                f'Conformance spec references non-canonical capability "{spec.capability.name}"'
            )
        if contract.version != spec.version:
            raise ValueError(
                f'Conformance spec version mismatch for "{spec.capability.name}": '
                f"expected v{contract.version}, got v{spec.version}"
            )
        registry[key] = spec
    return registry


def get_conformance_spec(
    specs: dict[tuple[str, int], CapabilityConformanceSpec],
    contract: CapabilityContract,
) -> CapabilityConformanceSpec | None:
    return specs.get(_spec_key(contract.capability, contract.version))


async def run_capability_conformance(
    *,
    descriptor: IntegrationDescriptor,
    capability: Capability | str,
    harness: object,
    specs: dict[tuple[str, int], CapabilityConformanceSpec],
) -> CapabilityConformanceResult:
    contract = get_capability_contract(capability)
    name = capability.name if isinstance(capability, Capability) else capability
    if contract is None:
        return CapabilityConformanceResult(
            capability=name,
            contract_version=0,
            failures=(
                ConformanceFailure(
                    kind=ConformanceFailureKind.REGISTRY,
                    capability=name,
                    message=f'No canonical Rakit contract exists for capability "{name}"',
                ),
            ),
        )

    advertisement_failures = tuple(
        failure
        for failure in validate_advertised_capabilities(descriptor)
        if failure.capability == contract.capability.name
    )
    if advertisement_failures:
        return CapabilityConformanceResult(
            capability=contract.capability.name,
            contract_version=contract.version,
            failures=advertisement_failures,
        )

    spec = get_conformance_spec(specs, contract)
    if spec is None:
        return CapabilityConformanceResult(
            capability=contract.capability.name,
            contract_version=contract.version,
            failures=(
                ConformanceFailure(
                    kind=ConformanceFailureKind.REGISTRY,
                    capability=contract.capability.name,
                    message=(
                        f"No conformance spec exists for canonical capability "
                        f'"{contract.capability.name}" v{contract.version}'
                    ),
                ),
            ),
        )

    failures: list[ConformanceFailure] = []
    for check in spec.checks:
        try:
            await check.run(harness)
        except AssertionError as exc:
            detail = str(exc).strip()
            message = f'Conformance check "{check.check_id}" failed'
            if detail:
                message = f"{message}: {detail}"
            failures.append(
                ConformanceFailure(
                    kind=ConformanceFailureKind.BEHAVIOR,
                    capability=contract.capability.name,
                    check_id=check.check_id,
                    message=message,
                )
            )

    return CapabilityConformanceResult(
        capability=contract.capability.name,
        contract_version=contract.version,
        failures=tuple(failures),
    )


def advertised_canonical_capabilities(
    descriptor: IntegrationDescriptor,
) -> CapabilitySet:
    return CapabilitySet.from_iterable(
        capability
        for capability in descriptor.advertised_capabilities.values
        if get_capability_contract(capability) is not None
    )


__all__ = [
    "CapabilityBehaviorCheck",
    "CapabilityConformanceResult",
    "CapabilityConformanceSpec",
    "ConformanceFailure",
    "ConformanceFailureKind",
    "IntegrationConformanceResult",
    "advertised_canonical_capabilities",
    "build_conformance_spec_registry",
    "get_conformance_spec",
    "run_capability_conformance",
    "validate_advertised_capabilities",
]