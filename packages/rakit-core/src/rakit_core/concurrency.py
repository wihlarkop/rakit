"""Signed optimistic-concurrency tokens for resource mutations."""

import hashlib
import json
import math
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from enum import Enum, StrEnum
from typing import Any, Protocol
from uuid import UUID

from rakit_core.crypto import TokenService
from rakit_core.errors import ErrorCode, RakitError
from rakit_core.identity import RecordIdentity


class ConcurrencyMode(StrEnum):
    AUTO = "auto"
    REQUIRED = "required"
    DISABLED = "disabled"


class ConcurrencyVersionProvider(Protocol):
    """Backend-neutral source for the version bound into a mutation token."""

    def version_for(self, record: object) -> Any: ...

    def predicate_values_for(self, record: object) -> Mapping[str, Any]: ...

    def next_values_for(self, record: object) -> Mapping[str, Any]: ...


@dataclass(frozen=True)
class AttributeVersionProvider:
    """Use one mapped scalar attribute as a concurrency version."""

    field: str

    def version_for(self, record: object) -> Any:
        return getattr(record, self.field)

    def predicate_values_for(self, record: object) -> Mapping[str, Any]:
        return {self.field: self.version_for(record)}

    def next_values_for(self, record: object) -> Mapping[str, Any]:
        value = self.version_for(record)
        if isinstance(value, int) and not isinstance(value, bool):
            return {self.field: value + 1}
        if isinstance(value, datetime):
            now = datetime.now(value.tzinfo or UTC)
            if value.tzinfo is None:
                now = now.replace(tzinfo=None)
            # Databases with coarse timestamp resolution must still get a
            # strictly new predicate value in this same SQL UPDATE.
            if now <= value:
                now = value + timedelta(microseconds=1)
            return {self.field: now}
        return {}


@dataclass(frozen=True)
class SnapshotVersionProvider:
    """Deterministic hash over explicitly safe scalar fields only."""

    fields: tuple[str, ...]

    def version_for(self, record: object) -> str:
        values = {
            field: _canonical_value(value)
            for field, value in self.predicate_values_for(record).items()
        }
        encoded = json.dumps(values, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        return hashlib.sha256(encoded.encode("utf-8")).hexdigest()

    def predicate_values_for(self, record: object) -> Mapping[str, Any]:
        return {field: getattr(record, field) for field in self.fields}

    def next_values_for(self, record: object) -> Mapping[str, Any]:
        return {}


@dataclass(frozen=True)
class ConcurrencyConflict:
    """Safe, structured context for rendering a stale-write conflict."""

    base: Mapping[str, Any]
    current: Mapping[str, Any]
    proposed: Mapping[str, Any]
    field_conflicts: tuple[str, ...]
    relationship_conflicts: tuple[str, ...] = ()

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "base": dict(self.base),
            "current": dict(self.current),
            "proposed": dict(self.proposed),
            "field_conflicts": list(self.field_conflicts),
            "relationship_conflicts": list(self.relationship_conflicts),
        }


def _canonical_value(value: Any) -> Any:
    if isinstance(value, datetime):
        # SQLite and several SQLAlchemy dialect configurations return a naive
        # value for a UTC column. Treat that representation as UTC so the
        # token remains stable across the create/read boundary.
        normalized = value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
        return normalized.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, UUID | Decimal):
        return str(value)
    if isinstance(value, Enum):
        return _canonical_value(value.value)
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("Snapshot concurrency floats must be finite")
        return value
    if isinstance(value, str | int | bool) or value is None:
        return value
    raise ValueError("Snapshot concurrency values must be scalar and canonical")


class ConcurrencyTokenService:
    """Issues purpose-separated tokens bound to one identity and revision."""

    def __init__(
        self, token_service: TokenService, *, ttl: timedelta = timedelta(minutes=15)
    ) -> None:
        self._token_service = token_service
        self._ttl = ttl

    def issue(
        self,
        resource_id: str,
        identity: RecordIdentity,
        version: Any,
        *,
        base_snapshot: Mapping[str, Any] | None = None,
    ) -> str:
        base = self.canonical_snapshot(base_snapshot or {})
        return self._token_service.issue_in(
            "concurrency",
            {
                "resource_id": resource_id,
                "identity": dict(identity.values),
                "version": _canonical_value(version),
                "base_snapshot": base,
            },
            self._ttl,
        )

    @staticmethod
    def canonical_snapshot(values: Mapping[str, Any]) -> dict[str, Any]:
        """Return the sole JSON-safe representation used by token and conflicts."""
        return {key: _canonical_value(value) for key, value in values.items()}

    def base_snapshot(
        self, token: str, resource_id: str, identity: RecordIdentity
    ) -> Mapping[str, Any]:
        try:
            claims = self._token_service.verify(token, expected_purpose="concurrency")
        except ValueError as exc:
            raise self._conflict() from exc
        if claims.get("resource_id") != resource_id or claims.get("identity") != dict(
            identity.values
        ):
            raise self._conflict()
        snapshot = claims.get("base_snapshot", {})
        if not isinstance(snapshot, Mapping):
            raise self._conflict()
        return dict(snapshot)

    def verify(
        self, token: str, resource_id: str, identity: RecordIdentity, version: Any
    ) -> Mapping[str, Any]:
        snapshot = self.base_snapshot(token, resource_id, identity)
        try:
            claims = self._token_service.verify(token, expected_purpose="concurrency")
        except ValueError as exc:
            raise self._conflict() from exc
        if claims.get("version") != _canonical_value(version):
            raise self._conflict()
        return snapshot

    @staticmethod
    def _conflict() -> RakitError:
        return RakitError(
            code=ErrorCode.RESOURCE_CONFLICT,
            message="The resource has changed since this form was opened.",
            status_code=409,
        )
