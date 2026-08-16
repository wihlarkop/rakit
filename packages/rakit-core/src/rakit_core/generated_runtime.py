from dataclasses import dataclass
from typing import Protocol

from .concurrency import ConcurrencyTokenService, ConcurrencyVersionProvider
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
class ResourceAdapterRuntime:
    data_source: DataSource
    generated_executor_provider: GeneratedResourceExecutorProvider | None = None


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
    "normalize_resource_adapter_runtime",
]
