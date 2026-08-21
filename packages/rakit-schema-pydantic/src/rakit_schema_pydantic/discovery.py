from rakit_core.integrations import IntegrationDescriptor

from .capabilities import PYDANTIC_SCHEMA_CAPABILITIES

PYDANTIC_INTEGRATION = IntegrationDescriptor(
    integration_id="schema.pydantic",
    category="schema",
    display_name="Pydantic",
    advertised_capabilities=PYDANTIC_SCHEMA_CAPABILITIES.capabilities,
)

__all__ = ["PYDANTIC_INTEGRATION"]
