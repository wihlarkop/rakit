from rakit_core.adapter_capabilities import (
    SCHEMA_FIELD_INTROSPECTION,
    SCHEMA_INPUT_VALIDATION,
    SCHEMA_OUTPUT_SERIALIZATION,
    SCHEMA_PARTIAL_UPDATE,
)
from rakit_core.capabilities import CapabilityProvider, CapabilitySet

PYDANTIC_SCHEMA_CAPABILITIES = CapabilityProvider(
    provider_id="schema.pydantic",
    capabilities=CapabilitySet.of(
        SCHEMA_FIELD_INTROSPECTION,
        SCHEMA_INPUT_VALIDATION,
        SCHEMA_OUTPUT_SERIALIZATION,
        SCHEMA_PARTIAL_UPDATE,
    ),
)

__all__ = ["PYDANTIC_SCHEMA_CAPABILITIES"]
