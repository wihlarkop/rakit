from rakit_core.integrations import IntegrationDescriptor

from .capabilities import GRANIAN_SERVER_CAPABILITIES

GRANIAN_INTEGRATION = IntegrationDescriptor(
    integration_id="server.granian",
    category="server",
    display_name="Granian",
    advertised_capabilities=GRANIAN_SERVER_CAPABILITIES.capability_set,
)

__all__ = ["GRANIAN_INTEGRATION"]
