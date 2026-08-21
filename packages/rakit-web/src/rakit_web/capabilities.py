from rakit_core.adapter_capabilities import (
    SCHEMA_FIELD_INTROSPECTION,
    SCHEMA_INPUT_VALIDATION,
    SCHEMA_OUTPUT_SERIALIZATION,
    SCHEMA_PARTIAL_UPDATE,
    WEB_ASGI,
    WEB_HTTP_ROUTING,
    WEB_STREAMING_RESPONSE,
)
from rakit_core.capabilities import CapabilityProvider, CapabilitySet

STARLETTE_WEB_CAPABILITIES = CapabilityProvider(
    provider_id="web.starlette",
    capabilities=CapabilitySet.of(
        WEB_ASGI,
        WEB_HTTP_ROUTING,
        WEB_STREAMING_RESPONSE,
    ),
)

PYDANTIC_SCHEMA_CAPABILITIES = CapabilityProvider(
    provider_id="schema.pydantic",
    capabilities=CapabilitySet.of(
        SCHEMA_FIELD_INTROSPECTION,
        SCHEMA_INPUT_VALIDATION,
        SCHEMA_OUTPUT_SERIALIZATION,
        SCHEMA_PARTIAL_UPDATE,
    ),
)

__all__ = ["PYDANTIC_SCHEMA_CAPABILITIES", "STARLETTE_WEB_CAPABILITIES"]
