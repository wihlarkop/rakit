from dataclasses import dataclass
from typing import Protocol

from .admin_types import ResourceWriteDefinition
from .concurrency import ConcurrencyTokenService, ConcurrencyVersionProvider
from .crypto import TokenService
from .datasource import DataSource
from .generated_operations import GeneratedResourceExecutor


@dataclass(frozen=True, slots=True)
class GeneratedResourceExecutorContext:
    resource_id: str
    data_source: DataSource
    concurrency_provider: ConcurrencyVersionProvider | None = None
    concurrency_tokens: ConcurrencyTokenService | None = None


class GeneratedResourceExecutorProvider(Protocol):
    def build(self, context: GeneratedResourceExecutorContext) -> GeneratedResourceExecutor: ...


@dataclass(frozen=True, slots=True)
class ResourceWriteServiceContext:
    """Neutral context an adapter needs to materialize ordinary CRUD."""

    admin_id: str
    resource_id: str
    definition: ResourceWriteDefinition
    token_service: TokenService


class ResourceWriteServiceProvider(Protocol):
    """Adapter capability for building a concrete resource mutation service."""

    def build(self, context: ResourceWriteServiceContext) -> object: ...


@dataclass(frozen=True, slots=True)
class ResourceAdapterRuntime:
    data_source: DataSource
    generated_executor_provider: GeneratedResourceExecutorProvider | None = None
    write_service_provider: ResourceWriteServiceProvider | None = None
    unit_of_work_provider_id: str | None = None


def normalize_resource_adapter_runtime(
    candidate: DataSource | ResourceAdapterRuntime,
) -> ResourceAdapterRuntime:
    if isinstance(candidate, ResourceAdapterRuntime):
        return candidate
    return ResourceAdapterRuntime(data_source=candidate)


__all__ = [
    "GeneratedResourceExecutorContext",
    "GeneratedResourceExecutorProvider",
    "ResourceAdapterRuntime",
    "ResourceWriteServiceContext",
    "ResourceWriteServiceProvider",
    "normalize_resource_adapter_runtime",
]
