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
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from rakit_core._immutability import freeze_mapping
from rakit_core.concurrency import ConcurrencyTokenService
from rakit_core.events import DomainEvent
from rakit_core.identity import RecordIdentity, canonical_identity_payload
from rakit_core.permissions import PermissionRequirement


class RelationshipMutationKind(StrEnum):
    """Semantic operations supported by the relationship executor."""

    SET = "set"
    CLEAR = "clear"
    ADD = "add"
    UPDATE = "update"
    REMOVE = "remove"
    REPLACE = "replace"


class RelationshipGraphStep(BaseModel):
    """Base for the explicit child/edge intents of a composed resource write."""

    model_config = ConfigDict(frozen=True, extra="forbid")


class CreateRelated(RelationshipGraphStep):
    kind: Literal["create"] = "create"
    values: Mapping[str, Any]

    @field_validator("values")
    @classmethod
    def _freeze_values(cls, value: Mapping[str, Any]) -> Mapping[str, Any]:
        if not value or any(not isinstance(key, str) or not key for key in value):
            raise ValueError("child values must have non-empty field identifiers")
        return freeze_mapping(ConcurrencyTokenService.canonical_snapshot(value))


class UpdateRelated(RelationshipGraphStep):
    kind: Literal["update"] = "update"
    identity: RecordIdentity
    values: Mapping[str, Any]
    concurrency_token: str | None = None

    @field_validator("values")
    @classmethod
    def _freeze_values(cls, value: Mapping[str, Any]) -> Mapping[str, Any]:
        if not value or any(not isinstance(key, str) or not key for key in value):
            raise ValueError("child values must have non-empty field identifiers")
        return freeze_mapping(ConcurrencyTokenService.canonical_snapshot(value))


class LinkRelated(RelationshipGraphStep):
    kind: Literal["link"] = "link"
    identity: RecordIdentity


class SetRelated(RelationshipGraphStep):
    """Set the single target of a to-one relationship."""

    kind: Literal["set"] = "set"
    identity: RecordIdentity


class ClearRelated(RelationshipGraphStep):
    """Clear the target of a nullable to-one relationship."""

    kind: Literal["clear"] = "clear"


class UnlinkRelated(RelationshipGraphStep):
    kind: Literal["unlink"] = "unlink"
    identity: RecordIdentity


class DeleteRelated(RelationshipGraphStep):
    """Delete a related child using its signed delete confirmation.

    The confirmation's resource/identity/expected-version binding is the
    authoritative child-delete concurrency proof.  A separate update token
    would be redundant and is deliberately not accepted by this model.
    """

    kind: Literal["delete"] = "delete"
    identity: RecordIdentity
    confirmation_token: str | None = None


class UpdateAssociationRelated(RelationshipGraphStep):
    """Change explicitly approved scalar values on one association edge."""

    kind: Literal["association_update"] = "association_update"
    target_identity: RecordIdentity
    values: Mapping[str, Any]
    association_identity: RecordIdentity | None = None

    @field_validator("values")
    @classmethod
    def _freeze_values(cls, value: Mapping[str, Any]) -> Mapping[str, Any]:
        if not value or any(not isinstance(key, str) or not key for key in value):
            raise ValueError("association scalar values must have non-empty field identifiers")
        return freeze_mapping(ConcurrencyTokenService.canonical_snapshot(value))


class ReorderRelated(RelationshipGraphStep):
    kind: Literal["reorder"] = "reorder"
    identities: tuple[RecordIdentity, ...]

    @field_validator("identities")
    @classmethod
    def _require_unique_order(cls, value: tuple[RecordIdentity, ...]) -> tuple[RecordIdentity, ...]:
        if not value:
            raise ValueError("reorder requires identities")
        if len({_identity_key(identity) for identity in value}) != len(value):
            raise ValueError("reorder contains duplicate identities")
        return value


type RelationshipMutationStep = Annotated[
    CreateRelated
    | UpdateRelated
    | LinkRelated
    | SetRelated
    | ClearRelated
    | UnlinkRelated
    | DeleteRelated
    | UpdateAssociationRelated
    | ReorderRelated,
    Field(discriminator="kind"),
]


class RelationshipChangePlan(BaseModel):
    """Immutable child/edge work attached to one parent graph mutation.

    It intentionally carries normalized scalar values and identities only.  A
    backend adapter resolves target write services and relationship metadata
    before applying it in the root operation's UoW.
    """

    model_config = ConfigDict(frozen=True)

    operation_id: str
    relationship_id: str
    steps: tuple[RelationshipMutationStep, ...]
    authorization_requirement: PermissionRequirement
    concurrency_token: str | None = None
    destructive_confirmation: str | None = None

    @field_validator("operation_id", "relationship_id")
    @classmethod
    def _require_relationship_id(cls, value: str) -> str:
        if not value:
            raise ValueError("relationship_id must not be empty")
        return value

    @field_validator("steps")
    @classmethod
    def _require_steps(
        cls, value: tuple[RelationshipMutationStep, ...]
    ) -> tuple[RelationshipMutationStep, ...]:
        if not value:
            raise ValueError("relationship change requires at least one step")
        return value

    @property
    def fingerprint_payload(self) -> dict[str, Any]:
        def identity(identity: RecordIdentity) -> Mapping[str, Any]:
            return canonical_identity_payload(identity)

        values: list[dict[str, Any]] = []
        for step in self.steps:
            payload: dict[str, Any] = {"kind": step.kind}
            if isinstance(step, CreateRelated):
                payload["values"] = dict(step.values)
            elif isinstance(step, UpdateRelated):
                payload.update(identity=identity(step.identity), values=dict(step.values))
            elif isinstance(step, LinkRelated | SetRelated | UnlinkRelated | DeleteRelated):
                payload["identity"] = identity(step.identity)
            elif isinstance(step, UpdateAssociationRelated):
                payload.update(
                    target_identity=identity(step.target_identity),
                    association_identity=(
                        identity(step.association_identity)
                        if step.association_identity is not None
                        else None
                    ),
                    values=dict(step.values),
                )
            elif isinstance(step, ReorderRelated):
                payload["identities"] = [identity(value) for value in step.identities]
            values.append(payload)
        return {
            "operation_id": self.operation_id,
            "relationship_id": self.relationship_id,
            "steps": values,
        }


def _identity_key(identity: RecordIdentity) -> str:
    return json.dumps(canonical_identity_payload(identity), sort_keys=True, separators=(",", ":"))


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


class RelationshipEditorRow(BaseModel):
    """Safe, adapter-produced state for one relationship editor row.

    This is read-side presentation data, not another mutation model.  The
    adapter has already applied parent and target visibility before exposing a
    row; the web layer still submits only canonical identities and the typed
    graph steps below remain the authoritative write contract.
    """

    model_config = ConfigDict(frozen=True)

    candidate: RelationshipCandidate
    values: Mapping[str, Any] = Field(default_factory=dict)
    association_identity: RecordIdentity | None = None
    concurrency_token: str | None = None

    @field_validator("values")
    @classmethod
    def _freeze_values(cls, value: Mapping[str, Any]) -> Mapping[str, Any]:
        if any(not isinstance(key, str) or not key for key in value):
            raise ValueError("editor values must have non-empty field identifiers")
        return freeze_mapping(value)


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
            "parent_identity": canonical_identity_payload(self.parent_identity),
            "relationship_id": self.relationship_id,
            "kind": self.kind.value,
            "target_identities": [
                canonical_identity_payload(identity) for identity in self.target_identities
            ],
            "association_changes": [
                {
                    "target_identity": canonical_identity_payload(change.target_identity),
                    "association_identity": (
                        canonical_identity_payload(change.association_identity)
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
    "ClearRelated",
    "CreateRelated",
    "DeleteRelated",
    "LinkRelated",
    "RelationshipCandidate",
    "RelationshipChangePlan",
    "RelationshipChanged",
    "RelationshipEditorRow",
    "RelationshipMutationKind",
    "RelationshipMutationPlan",
    "RelationshipMutationResult",
    "RelationshipMutationStep",
    "ReorderRelated",
    "SetRelated",
    "UnlinkRelated",
    "UpdateAssociationRelated",
    "UpdateRelated",
]
