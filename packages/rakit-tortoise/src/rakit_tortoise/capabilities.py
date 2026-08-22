from rakit_core.adapter_capabilities import PERSISTENCE_READ
from rakit_core.capabilities import CapabilityProvider, CapabilitySet

TORTOISE_CAPABILITIES = CapabilityProvider(
    provider_id="persistence.tortoise",
    capabilities=CapabilitySet.of(PERSISTENCE_READ),
)

__all__ = ["TORTOISE_CAPABILITIES"]
