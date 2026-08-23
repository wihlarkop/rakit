from rakit_core.adapter_capabilities import (
    PERSISTENCE_READ,
    PERSISTENCE_WRITE,
    TRANSACTIONS_ROOT_UOW,
)
from rakit_core.capabilities import CapabilityProvider, CapabilitySet

PICCOLO_CAPABILITIES = CapabilityProvider(
    provider_id="persistence.piccolo",
    capabilities=CapabilitySet.of(
        PERSISTENCE_READ,
        PERSISTENCE_WRITE,
        TRANSACTIONS_ROOT_UOW,
    ),
)

__all__ = ["PICCOLO_CAPABILITIES"]
