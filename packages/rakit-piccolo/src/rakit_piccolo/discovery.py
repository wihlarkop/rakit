from rakit_core.integrations import IntegrationDescriptor

from .capabilities import PICCOLO_CAPABILITIES

PICCOLO_INTEGRATION = IntegrationDescriptor(
    integration_id="persistence.piccolo",
    category="persistence",
    display_name="Piccolo ORM",
    advertised_capabilities=PICCOLO_CAPABILITIES.capabilities,
)

__all__ = ["PICCOLO_INTEGRATION"]
