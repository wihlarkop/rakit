from rakit_core.integrations import IntegrationDescriptor

from .capabilities import UVICORN_SERVER_CAPABILITIES

UVICORN_INTEGRATION = IntegrationDescriptor(
    integration_id="server.uvicorn",
    category="server",
    display_name="Uvicorn",
    advertised_capabilities=UVICORN_SERVER_CAPABILITIES.capability_set,
)

__all__ = ["UVICORN_INTEGRATION"]
