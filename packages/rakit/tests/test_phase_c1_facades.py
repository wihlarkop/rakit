from rakit import ResourceWriteDefinition
from rakit.core import ResourceWriteServiceContext, ResourceWriteServiceProvider
from rakit_core.admin_types import ResourceWriteDefinition as CoreResourceWriteDefinition
from rakit_core.generated_runtime import (
    ResourceWriteServiceContext as CoreResourceWriteServiceContext,
)
from rakit_core.generated_runtime import (
    ResourceWriteServiceProvider as CoreResourceWriteServiceProvider,
)


def test_c1_write_declaration_uses_canonical_root_facade() -> None:
    assert ResourceWriteDefinition is CoreResourceWriteDefinition


def test_c1_write_provider_contracts_use_canonical_core_facade() -> None:
    assert ResourceWriteServiceContext is CoreResourceWriteServiceContext
    assert ResourceWriteServiceProvider is CoreResourceWriteServiceProvider
