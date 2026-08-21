from rakit_core.integrations import IntegrationDescriptor

from .capabilities import SQLALCHEMY_CAPABILITIES

SQLALCHEMY_INTEGRATION = IntegrationDescriptor(
    integration_id="persistence.sqlalchemy",
    category="persistence",
    display_name="SQLAlchemy",
    advertised_capabilities=SQLALCHEMY_CAPABILITIES.capabilities,
)

__all__ = ["SQLALCHEMY_INTEGRATION"]
