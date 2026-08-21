from rakit_core.adapter_capabilities import (
    WEB_ASGI,
    WEB_HTTP_ROUTING,
    WEB_STREAMING_RESPONSE,
)
from rakit_core.capabilities import CapabilityProvider, CapabilitySet

STARLETTE_WEB_CAPABILITIES = CapabilityProvider(
    provider_id="web.starlette",
    capabilities=CapabilitySet.of(
        WEB_ASGI,
        WEB_HTTP_ROUTING,
        WEB_STREAMING_RESPONSE,
    ),
)

__all__ = ["STARLETTE_WEB_CAPABILITIES"]
