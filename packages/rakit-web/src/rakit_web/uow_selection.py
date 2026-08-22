from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from rakit_core.transactions import OperationUnitOfWorkFactory


@dataclass(frozen=True, slots=True)
class ResourceUnitOfWorkRegistry:
    """Resolve operation transaction factories without install-order guessing."""

    factories: Mapping[str, OperationUnitOfWorkFactory]
    resource_provider_ids: Mapping[str, str]

    @property
    def provider_count(self) -> int:
        return len(self.factories)

    @property
    def has_any_provider(self) -> bool:
        return bool(self.factories)

    def for_resource(self, resource_id: str) -> OperationUnitOfWorkFactory | None:
        provider_id = self.resource_provider_ids.get(resource_id)
        if provider_id is None:
            return None
        return self.factories.get(provider_id)

    def sole_provider(self) -> OperationUnitOfWorkFactory | None:
        if len(self.factories) != 1:
            return None
        return next(iter(self.factories.values()))


__all__ = ["ResourceUnitOfWorkRegistry"]
