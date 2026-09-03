from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from rakit_core.concurrency import ConcurrencyVersionProvider


@dataclass(frozen=True, slots=True)
class MappingVersionProvider(ConcurrencyVersionProvider):
    """Integer version-column concurrency for SQLAlchemy Core mapping rows.

    SQLAlchemy Core data sources deliberately expose rows as plain mappings,
    so the neutral attribute-based provider cannot read them.  This provider
    keeps that representation detail inside the Core adapter while preserving
    the backend-neutral concurrency contract.
    """

    field: str = "version"

    def _version(self, record: object) -> int:
        if not isinstance(record, Mapping):
            raise TypeError("SQLAlchemy Core concurrency records must be mapping values")
        value = record.get(self.field)
        if isinstance(value, bool) or not isinstance(value, int):
            raise TypeError("SQLAlchemy Core version values must be integers")
        return value

    def version_for(self, record: object) -> int:
        return self._version(record)

    def predicate_values_for(self, record: object) -> Mapping[str, object]:
        return {self.field: self._version(record)}

    def next_values_for(self, record: object) -> Mapping[str, object]:
        return {self.field: self._version(record) + 1}


__all__ = ["MappingVersionProvider"]
