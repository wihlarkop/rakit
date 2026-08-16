from collections.abc import Iterable
from dataclasses import dataclass, field

from .errors import ErrorCode, RakitError


@dataclass(frozen=True, slots=True, order=True)
class Capability:
    name: str

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError("Capability name must not be empty")
        if self.name != self.name.strip():
            raise ValueError("Capability name must not contain surrounding whitespace")

    def __str__(self) -> str:
        return self.name


def _coerce_capability(value: Capability | str) -> Capability:
    return value if isinstance(value, Capability) else Capability(value)


@dataclass(frozen=True, slots=True)
class CapabilitySet:
    values: frozenset[Capability] = field(default_factory=frozenset)

    @classmethod
    def of(cls, *values: Capability | str) -> "CapabilitySet":
        return cls(frozenset(_coerce_capability(value) for value in values))

    @classmethod
    def from_iterable(cls, values: Iterable[Capability | str]) -> "CapabilitySet":
        return cls(frozenset(_coerce_capability(value) for value in values))

    @property
    def names(self) -> tuple[str, ...]:
        return tuple(sorted(capability.name for capability in self.values))

    def supports(self, capability: Capability | str) -> bool:
        return _coerce_capability(capability) in self.values

    def union(self, *others: "CapabilitySet") -> "CapabilitySet":
        merged = set(self.values)
        for other in others:
            merged.update(other.values)
        return CapabilitySet(frozenset(merged))

    def difference(self, other: "CapabilitySet") -> "CapabilitySet":
        return CapabilitySet(self.values.difference(other.values))


@dataclass(frozen=True, slots=True)
class CapabilityProvider:
    provider_id: str
    capabilities: CapabilitySet

    def __post_init__(self) -> None:
        if not self.provider_id:
            raise ValueError("Capability provider id must not be empty")
        if self.provider_id != self.provider_id.strip():
            raise ValueError("Capability provider id must not contain surrounding whitespace")


@dataclass(frozen=True, slots=True)
class CapabilityRequirement:
    requirement_id: str
    required: CapabilitySet

    def __post_init__(self) -> None:
        if not self.requirement_id:
            raise ValueError("Capability requirement id must not be empty")
        if self.requirement_id != self.requirement_id.strip():
            raise ValueError("Capability requirement id must not contain surrounding whitespace")

    @classmethod
    def of(cls, requirement_id: str, *required: Capability | str) -> "CapabilityRequirement":
        return cls(requirement_id=requirement_id, required=CapabilitySet.of(*required))


@dataclass(frozen=True, slots=True)
class CapabilityReport:
    requirement: CapabilityRequirement
    providers: tuple[CapabilityProvider, ...]
    available: CapabilitySet
    missing: CapabilitySet

    @property
    def satisfied(self) -> bool:
        return not self.missing.values

    @property
    def provider_ids(self) -> tuple[str, ...]:
        return tuple(provider.provider_id for provider in self.providers)


def evaluate_capabilities(
    requirement: CapabilityRequirement,
    providers: Iterable[CapabilityProvider],
) -> CapabilityReport:
    provider_tuple = tuple(providers)
    available = CapabilitySet()
    for provider in provider_tuple:
        available = available.union(provider.capabilities)
    missing = requirement.required.difference(available)
    return CapabilityReport(
        requirement=requirement,
        providers=provider_tuple,
        available=available,
        missing=missing,
    )


def require_capabilities(
    requirement: CapabilityRequirement,
    providers: Iterable[CapabilityProvider],
) -> CapabilityReport:
    report = evaluate_capabilities(requirement, providers)
    if report.satisfied:
        return report
    raise RakitError(
        code=ErrorCode.CONFIG_INVALID,
        message=(
            f'Capability requirement "{requirement.requirement_id}" is not satisfied; '
            f"missing: {', '.join(report.missing.names)}."
        ),
        status_code=500,
        details={
            "requirement": requirement.requirement_id,
            "required": list(requirement.required.names),
            "available": list(report.available.names),
            "missing": list(report.missing.names),
            "providers": list(report.provider_ids),
            "reason": "missing_capabilities",
        },
    )
