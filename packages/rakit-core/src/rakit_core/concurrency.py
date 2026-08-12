"""Signed optimistic-concurrency tokens for resource mutations."""

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Any, Protocol

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


@dataclass(frozen=True)
class AttributeVersionProvider:
    """Use one mapped scalar attribute as a concurrency version."""

    field: str

    def version_for(self, record: object) -> Any:
        return getattr(record, self.field)


@dataclass(frozen=True)
class SnapshotVersionProvider:
    """Deterministic hash over explicitly safe scalar fields only."""

    fields: tuple[str, ...]

    def version_for(self, record: object) -> str:
        values = {field: _canonical_value(getattr(record, field)) for field in self.fields}
        encoded = json.dumps(values, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


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
        return value.isoformat()
    if isinstance(value, str | int | float | bool) or value is None:
        return value
    raise ValueError("Snapshot concurrency values must be scalar and canonical")


class ConcurrencyTokenService:
    """Issues purpose-separated tokens bound to one identity and revision."""

    def __init__(
        self, token_service: TokenService, *, ttl: timedelta = timedelta(minutes=15)
    ) -> None:
        self._token_service = token_service
        self._ttl = ttl

    def issue(self, resource_id: str, identity: RecordIdentity, version: Any) -> str:
        return self._token_service.issue_in(
            "concurrency",
            {
                "resource_id": resource_id,
                "identity": dict(identity.values),
                "version": _canonical_value(version),
            },
            self._ttl,
        )

    def verify(self, token: str, resource_id: str, identity: RecordIdentity, version: Any) -> None:
        try:
            claims = self._token_service.verify(token, expected_purpose="concurrency")
        except ValueError as exc:
            raise self._conflict() from exc
        if (
            claims.get("resource_id") != resource_id
            or claims.get("identity") != dict(identity.values)
            or claims.get("version") != _canonical_value(version)
        ):
            raise self._conflict()

    @staticmethod
    def _conflict() -> RakitError:
        return RakitError(
            code=ErrorCode.RESOURCE_CONFLICT,
            message="The resource has changed since this form was opened.",
            status_code=409,
        )
