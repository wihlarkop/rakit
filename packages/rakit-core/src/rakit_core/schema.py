from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol

from .capabilities import CapabilityProvider


@dataclass(frozen=True, slots=True)
class SchemaField:
    name: str
    title: str | None = None
    description: str | None = None


@dataclass(frozen=True, slots=True)
class SchemaValidationIssue:
    location: tuple[str, ...]
    code: str
    message: str


class SchemaValidationError(ValueError):
    def __init__(self, issues: tuple[SchemaValidationIssue, ...]) -> None:
        if not issues:
            raise ValueError("SchemaValidationError requires at least one issue")
        self.issues = issues
        super().__init__("Schema validation failed")


class SchemaAdapter(Protocol):
    """Backend-neutral validation seam used by generated transports.

    Concrete schema engines own validation and serialization details. Core
    consumers depend only on this contract and on the provider's declared
    capabilities; they must not infer support from implementation type names.
    """

    provider: CapabilityProvider

    def fields(self, schema: type[object]) -> tuple[SchemaField, ...]: ...

    def field_names(self, schema: type[object]) -> tuple[str, ...]: ...

    def validate_input(
        self,
        schema: type[object],
        values: Mapping[str, object],
    ) -> object: ...

    def serialize_output(self, schema: type[object], value: object) -> object: ...


__all__ = [
    "SchemaAdapter",
    "SchemaField",
    "SchemaValidationError",
    "SchemaValidationIssue",
]
