from rakit_core.integrations import IntegrationDescriptor

from .capabilities import STARLETTE_WEB_CAPABILITIES

STARLETTE_INTEGRATION = IntegrationDescriptor(
    integration_id="web.starlette",
    category="web",
    display_name="Starlette",
    advertised_capabilities=STARLETTE_WEB_CAPABILITIES.capabilities,
)

__all__ = ["STARLETTE_INTEGRATION"]
