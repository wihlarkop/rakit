from rakit_core.integrations import IntegrationDescriptor

from .capabilities import MSGSPEC_SCHEMA_CAPABILITIES

MSGSPEC_INTEGRATION = IntegrationDescriptor(
    integration_id="schema.msgspec",
    category="schema",
    display_name="msgspec",
    advertised_capabilities=MSGSPEC_SCHEMA_CAPABILITIES.capabilities,
)

__all__ = ["MSGSPEC_INTEGRATION"]
