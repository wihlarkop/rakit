from dataclasses import dataclass, field

from .capabilities import CapabilitySet


def _validate_text(field_name: str, value: str) -> None:
    if not value or value != value.strip():
        raise ValueError(f"{field_name} must be a non-empty trimmed string")


@dataclass(frozen=True, slots=True)
class IntegrationDescriptor:
    integration_id: str
    category: str
    display_name: str
    advertised_capabilities: CapabilitySet = field(default_factory=CapabilitySet)

    def __post_init__(self) -> None:
        _validate_text("integration_id", self.integration_id)
        _validate_text("category", self.category)
        _validate_text("display_name", self.display_name)


@dataclass(frozen=True, slots=True)
class ConfiguredIntegration:
    integration_id: str | None
    category: str
    display_name: str

    def __post_init__(self) -> None:
        if self.integration_id is not None:
            _validate_text("integration_id", self.integration_id)
        _validate_text("category", self.category)
        _validate_text("display_name", self.display_name)

    @classmethod
    def from_descriptor(cls, descriptor: IntegrationDescriptor) -> "ConfiguredIntegration":
        return cls(
            integration_id=descriptor.integration_id,
            category=descriptor.category,
            display_name=descriptor.display_name,
        )


def integration_descriptor_from(source: object) -> IntegrationDescriptor | None:
    value = getattr(source, "rakit_integration", None)
    if value is None:
        return None
    if not isinstance(value, IntegrationDescriptor):
        raise TypeError("rakit_integration must be an IntegrationDescriptor")
    return value


__all__ = [
    "ConfiguredIntegration",
    "IntegrationDescriptor",
    "integration_descriptor_from",
]
