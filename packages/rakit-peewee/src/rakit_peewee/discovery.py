from rakit_core.integrations import IntegrationDescriptor

from .capabilities import PEEWEE_CAPABILITIES

PEEWEE_INTEGRATION = IntegrationDescriptor(
    integration_id="persistence.peewee",
    category="persistence",
    display_name="Peewee ORM",
    advertised_capabilities=PEEWEE_CAPABILITIES.capabilities,
)

__all__ = ["PEEWEE_INTEGRATION"]
