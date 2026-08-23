from rakit_core.adapter_capabilities import PERSISTENCE_READ
from rakit_core.capabilities import CapabilityProvider, CapabilitySet

PICCOLO_CAPABILITIES = CapabilityProvider(
    provider_id="persistence.piccolo",
    capabilities=CapabilitySet.of(PERSISTENCE_READ),
)

__all__ = ["PICCOLO_CAPABILITIES"]
