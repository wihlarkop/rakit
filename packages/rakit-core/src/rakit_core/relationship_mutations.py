"""Backend-neutral immutable plans and receipts for relationship writes.

The plan deliberately contains identities and safe scalar values only.  ORM
instances, sessions, mapper metadata, and web request state remain adapter
concerns so every relationship write can participate in the existing
operation/UoW lifecycle without creating a second mutation system.
"""

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, field_validator, model_validator

from rakit_core._immutability import freeze_mapping
from rakit_core.concurrency import ConcurrencyTokenService
from rakit_core.events import DomainEvent
from rakit_core.identity import RecordIdentity
from rakit_core.permissions import PermissionRequirement


class RelationshipMutationKind(StrEnum):
    """Semantic operations supported by the Plan 05 relationship executor."""

    SET = "set"
    CLEAR = "clear"
    ADD = "add"
    UPDATE = "update"
    REMOVE = "remove"
    REPLACE = "replace"


def _identity_key(identity: RecordIdentity) -> str:
    return json.dumps(dict(identity.values), sort_keys=True, separators=(",", ":"))


def _canonical_identities(
    identities: tuple[RecordIdentity, ...], *, field: str
) -> tuple[RecordIdentity, ...]:
    ordered = tuple(sorted(identities, key=_identity_key))
    if len({_identity_key(identity) for identity in ordered}) != len(ordered):
        raise ValueError(f"{field} contains duplicate identities")
    return ordered


class AssociationScalarChange(BaseModel):
    """Explicit, safe scalar changes for one association-object edge."""

    model_config = ConfigDict(frozen=True)

    target_identity: RecordIdentity
    values: Mapping[str, Any]
    association_identity: RecordIdentity | None = None

    @field_validator("values")
    @classmethod
    def _freeze_safe_scalar_values(cls, value: Mapping[str, Any]) -> Mapping[str, Any]:
        if not value or any(not isinstance(key, str) or not key for key in value):
            raise ValueError("association scalar values must have non-empty field identifiers")
        # Reuse the one canonical Plan 04 scalar encoder.  This keeps
        # relationship fingerprints compatible with concurrency snapshots and
        # rejects opaque/unsafe values before any adapter mutates ORM state.
        return freeze_mapping(ConcurrencyTokenService.canonical_snapshot(value))


class RelationshipCandidate(BaseModel):
    """A target option safe for a later transport/UI adapter to display."""

    model_config = ConfigDict(frozen=True)

    identity: RecordIdentity
    label: str

    @field_validator("label")
    @classmethod
    def _require_plain_text_label(cls, value: str) -> str:
        if not value:
            raise ValueError("relationship candidate label must not be empty")
        return value


class RelationshipMutationPlan(BaseModel):
    """Canonical request-independent relationship mutation intent."""

    model_config = ConfigDict(frozen=True)

    operation_id: str
    parent_resource_id: str
    parent_identity: RecordIdentity
    relationship_id: str
    kind: RelationshipMutationKind
    target_identities: tuple[RecordIdentity, ...] = ()
    association_changes: tuple[AssociationScalarChange, ...] = ()
    authorization_requirement: PermissionRequirement
    concurrency_token: str | None = None
    idempotency_token: str | None = None
    destructive_confirmation: str | None = None

    @field_validator("operation_id", "parent_resource_id", "relationship_id")
    @classmethod
    def _require_nonempty_identifier(cls, value: str) -> str:
        if not value:
            raise ValueError("relationship mutation identifiers must not be empty")
        return value

    @field_validator("target_identities")
    @classmethod
    def _canonicalize_targets(cls, value: tuple[RecordIdentity, ...]) -> tuple[RecordIdentity, ...]:
        return _canonical_identities(value, field="target_identities")

    @model_validator(mode="after")
    def _validate_semantics(self) -> "RelationshipMutationPlan":
        count = len(self.target_identities)
        if self.kind is RelationshipMutationKind.SET and count != 1:
            raise ValueError("SET requires exactly one target identity")
        if self.kind is RelationshipMutationKind.CLEAR and count:
            raise ValueError("CLEAR must not supply target identities")
        if (
            self.kind in {RelationshipMutationKind.ADD, RelationshipMutationKind.REMOVE}
            and not count
        ):
            raise ValueError(f"{self.kind.value.upper()} requires target identities")

        target_keys = {_identity_key(identity) for identity in self.target_identities}
        changes = tuple(
            sorted(
                self.association_changes, key=lambda change: _identity_key(change.target_identity)
            )
        )
        change_keys = [_identity_key(change.target_identity) for change in changes]
        if len(change_keys) != len(set(change_keys)):
            raise ValueError("association_changes contains duplicate target identities")
        if any(key not in target_keys for key in change_keys):
            raise ValueError("association_changes target must be present in target_identities")
        object.__setattr__(self, "association_changes", changes)
        return self

    @property
    def fingerprint(self) -> str:
        """Stable digest for durable idempotency, independent of input order."""

        payload = {
            "operation_id": self.operation_id,
            "parent_resource_id": self.parent_resource_id,
            "parent_identity": dict(self.parent_identity.values),
            "relationship_id": self.relationship_id,
            "kind": self.kind.value,
            "target_identities": [dict(identity.values) for identity in self.target_identities],
            "association_changes": [
                {
                    "target_identity": dict(change.target_identity.values),
                    "association_identity": (
                        dict(change.association_identity.values)
                        if change.association_identity is not None
                        else None
                    ),
                    "values": dict(change.values),
                }
                for change in self.association_changes
            ],
        }
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


class RelationshipMutationResult(BaseModel):
    """Safe semantic receipt returned by a committed relationship mutation."""

    model_config = ConfigDict(frozen=True)

    parent_identity: RecordIdentity
    relationship_id: str
    kind: RelationshipMutationKind
    target_identities: tuple[RecordIdentity, ...]
    added_target_identities: tuple[RecordIdentity, ...] = ()
    removed_target_identities: tuple[RecordIdentity, ...] = ()
    deleted_target_identities: tuple[RecordIdentity, ...] = ()
    concurrency_token: str | None = None
    replayed: bool = False

    @field_validator(
        "target_identities",
        "added_target_identities",
        "removed_target_identities",
        "deleted_target_identities",
    )
    @classmethod
    def _canonicalize_result_identities(
        cls, value: tuple[RecordIdentity, ...], info: Any
    ) -> tuple[RecordIdentity, ...]:
        return _canonical_identities(value, field=info.field_name)


@dataclass(frozen=True)
class RelationshipChanged(DomainEvent):
    """Deferred semantic success event, delivered only after the outer UoW commits."""

    parent_resource_id: str
    parent_identity: RecordIdentity
    relationship_id: str
    kind: RelationshipMutationKind
    added_target_identities: tuple[RecordIdentity, ...] = ()
    removed_target_identities: tuple[RecordIdentity, ...] = ()
    deleted_target_identities: tuple[RecordIdentity, ...] = ()
    operation_id: str = ""


__all__ = [
    "AssociationScalarChange",
    "RelationshipCandidate",
    "RelationshipChanged",
    "RelationshipMutationKind",
    "RelationshipMutationPlan",
    "RelationshipMutationResult",
]
