from rakit_core.integrations import IntegrationDescriptor

from .capabilities import TORTOISE_CAPABILITIES

TORTOISE_INTEGRATION = IntegrationDescriptor(
    integration_id="persistence.tortoise",
    category="persistence",
    display_name="Tortoise ORM",
    advertised_capabilities=TORTOISE_CAPABILITIES.capabilities,
)

__all__ = ["TORTOISE_INTEGRATION"]
