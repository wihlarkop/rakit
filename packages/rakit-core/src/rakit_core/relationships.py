"""Backend-neutral relationship declarations compiled by data-source adapters."""

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from rakit_core.config import MachineId
from rakit_core.permissions import PermissionRequirement

type RecordLabelResolver = Callable[[object], str]


class RelationshipKind(StrEnum):
    MANY_TO_ONE = "many_to_one"
    ONE_TO_ONE = "one_to_one"
    ONE_TO_MANY = "one_to_many"
    MANY_TO_MANY = "many_to_many"
    ASSOCIATION_OBJECT = "association_object"


class RelationshipCardinality(StrEnum):
    TO_ONE = "to_one"
    TO_MANY = "to_many"


class RelationshipEditMode(StrEnum):
    LINK = "link"
    INLINE = "inline"
    NESTED = "nested"
    READ_ONLY = "read_only"
    HIDDEN = "hidden"


class RelationshipDestructivePolicy(BaseModel):
    """Host policy; mapper cascade facts never enable this automatically."""

    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    allow_child_delete: bool = False
    allow_delete_orphan: bool = False
    allow_destructive_cascade: bool = False

    @property
    def permits_persistent_delete(self) -> bool:
        return self.allow_child_delete or self.allow_delete_orphan or self.allow_destructive_cascade


class RelationshipOrderingDefinition(BaseModel):
    """Explicit portable declaration of a writable relationship position field."""

    model_config = ConfigDict(frozen=True)

    position_field: MachineId


class RelationshipDefinition(BaseModel):
    """One explicit admin relationship surface.

    Structural facts are declared here and are verified against an adapter's
    mapper metadata at compilation.  The source resource owns this definition;
    `target_resource_id` keeps core independent of ORM classes.
    """

    model_config = ConfigDict(frozen=True)

    relationship_id: MachineId
    target_resource_id: MachineId
    label: str = Field(min_length=1)
    kind: RelationshipKind
    cardinality: RelationshipCardinality
    nullable: bool = False
    ordered: bool = False
    ordering: RelationshipOrderingDefinition | None = None
    self_referential: bool = False
    readable: bool = True
    edit_mode: RelationshipEditMode = RelationshipEditMode.READ_ONLY
    writable: bool = False
    permission: PermissionRequirement | None = None
    destructive_policy: RelationshipDestructivePolicy = Field(
        default_factory=RelationshipDestructivePolicy
    )
    association_fields: tuple[str, ...] = ()
    association_target_resource_id: MachineId | None = None
    record_label_field: str | None = None
    record_label_resolver: RecordLabelResolver | None = None
    loading_strategy: str = "selectin"
    max_nested_depth: int = Field(default=1, ge=1)

    @field_validator("association_fields")
    @classmethod
    def _unique_association_fields(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(value) != len(set(value)) or any(not field for field in value):
            raise ValueError("association_fields must be unique non-empty field identifiers")
        return value

    @field_validator("loading_strategy")
    @classmethod
    def _known_loading_strategy(cls, value: str) -> str:
        if value not in {"selectin", "joined", "lazy"}:
            raise ValueError("loading_strategy must be selectin, joined, or lazy")
        return value

    @model_validator(mode="after")
    def _validate_association_contract(self) -> "RelationshipDefinition":
        if self.kind is RelationshipKind.ASSOCIATION_OBJECT:
            if self.association_target_resource_id is None:
                raise ValueError("association objects require association_target_resource_id")
        elif self.association_target_resource_id is not None:
            raise ValueError("association_target_resource_id requires an association object")
        if self.record_label_field is not None and self.record_label_resolver is not None:
            raise ValueError("Specify either record_label_field or record_label_resolver, not both")
        if self.ordering is not None and not self.ordered:
            raise ValueError("ordering requires ordered=True")
        return self

    @property
    def effective_writable(self) -> bool:
        return self.writable and self.edit_mode not in {
            RelationshipEditMode.READ_ONLY,
            RelationshipEditMode.HIDDEN,
        }


def resolve_record_label(definition: RelationshipDefinition, record: object) -> str:
    """Resolve a plain-text label from an already-visible safe record view.

    This helper does not grant visibility and deliberately returns text only;
    any future HTML escaping/rendering remains a web-adapter responsibility.
    """

    if definition.record_label_resolver is not None:
        value = definition.record_label_resolver(record)
    elif definition.record_label_field is not None:
        if isinstance(record, Mapping):
            value = record.get(definition.record_label_field)
        else:
            value = getattr(record, definition.record_label_field, None)
    else:
        raise ValueError("Relationship does not declare a record label resolver")
    if not isinstance(value, str):
        raise TypeError("Record label resolver must return str")
    return value


class RelationshipMetadata(BaseModel):
    """Adapter-derived structural facts, kept free of adapter implementation types."""

    model_config = ConfigDict(frozen=True)

    relationship_id: MachineId
    kind: RelationshipKind
    cardinality: RelationshipCardinality
    nullable: bool
    ordered: bool
    reorderable: bool = False
    ordering_position_field: str | None = None
    self_referential: bool
    view_only: bool
    has_secondary: bool
    cascade_delete: bool
    delete_orphan: bool
    association_object_eligible: bool = False
    association_scalar_fields: tuple[str, ...] = ()
    association_target_relationship_id: str | None = None


@dataclass(frozen=True)
class CompiledRelationship:
    """The policy-resolved relationship surface for later operation phases."""

    source_resource_id: str
    definition: RelationshipDefinition
    mutation_permission: PermissionRequirement
    target_delete_permission: PermissionRequirement | None
    route_path: str
    target_create_permission: PermissionRequirement | None = None
    target_update_permission: PermissionRequirement | None = None
    ordering: RelationshipOrderingDefinition | None = None
