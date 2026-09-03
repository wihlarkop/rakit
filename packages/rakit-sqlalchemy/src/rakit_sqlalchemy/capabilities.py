from rakit_core.adapter_capabilities import (
    CONCURRENCY_ATOMIC_OPTIMISTIC,
    PERSISTENCE_READ,
    PERSISTENCE_RELATIONSHIPS,
    PERSISTENCE_WRITE,
    TRANSACTIONS_ROOT_UOW,
)
from rakit_core.capabilities import CapabilityProvider, CapabilitySet

SQLALCHEMY_CAPABILITIES = CapabilityProvider(
    provider_id="persistence.sqlalchemy",
    capabilities=CapabilitySet.of(
        PERSISTENCE_READ,
        PERSISTENCE_WRITE,
        PERSISTENCE_RELATIONSHIPS,
        TRANSACTIONS_ROOT_UOW,
        CONCURRENCY_ATOMIC_OPTIMISTIC,
    ),
)

# Core reaches the same neutral behavioral contract through native Table/FK
# semantics; this capability set does not imply ORM mapper emulation.
SQLALCHEMY_CORE_CAPABILITIES = CapabilityProvider(
    provider_id="persistence.sqlalchemy-core",
    capabilities=CapabilitySet.of(
        PERSISTENCE_READ,
        PERSISTENCE_WRITE,
        PERSISTENCE_RELATIONSHIPS,
        TRANSACTIONS_ROOT_UOW,
        CONCURRENCY_ATOMIC_OPTIMISTIC,
    ),
)

__all__ = ["SQLALCHEMY_CAPABILITIES", "SQLALCHEMY_CORE_CAPABILITIES"]
