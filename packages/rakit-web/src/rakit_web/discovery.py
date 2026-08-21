from rakit_core.integrations import IntegrationDescriptor

from .capabilities import PYDANTIC_SCHEMA_CAPABILITIES, STARLETTE_WEB_CAPABILITIES

STARLETTE_INTEGRATION = IntegrationDescriptor(
    integration_id="web.starlette",
    category="web",
    display_name="Starlette",
    advertised_capabilities=STARLETTE_WEB_CAPABILITIES.capabilities,
)

PYDANTIC_INTEGRATION = IntegrationDescriptor(
    integration_id="schema.pydantic",
    category="schema",
    display_name="Pydantic",
    advertised_capabilities=PYDANTIC_SCHEMA_CAPABILITIES.capabilities,
)

__all__ = ["PYDANTIC_INTEGRATION", "STARLETTE_INTEGRATION"]
