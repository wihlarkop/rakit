from rakit_core.adapter_capabilities import (
    PERSISTENCE_READ,
    PERSISTENCE_WRITE,
    TRANSACTIONS_ROOT_UOW,
)
from rakit_core.capabilities import CapabilityProvider, CapabilitySet

PEEWEE_CAPABILITIES = CapabilityProvider(
    provider_id="persistence.peewee",
    capabilities=CapabilitySet.of(
        PERSISTENCE_READ,
        PERSISTENCE_WRITE,
        TRANSACTIONS_ROOT_UOW,
    ),
)

__all__ = ["PEEWEE_CAPABILITIES"]
