"""SQLAlchemy mapper inspection for Plan 05 relationship metadata."""

from typing import Any

from rakit_core.errors import ErrorCode, RakitError
from rakit_core.relationships import (
    RelationshipCardinality,
    RelationshipDefinition,
    RelationshipKind,
    RelationshipMetadata,
)
from sqlalchemy import Column, Integer, inspect
from sqlalchemy.orm import RelationshipProperty
from sqlalchemy.schema import PrimaryKeyConstraint, UniqueConstraint


def _foreign_key_columns(property_: RelationshipProperty[object]) -> tuple[Column[Any], ...]:
    """Return the actual FK side of this relationship, independent of direction."""

    columns: set[Column[Any]] = {
        column
        for local, remote in (property_.local_remote_pairs or ())
        for column in (local, remote)
        if isinstance(column, Column) and column.foreign_keys
    }
    return tuple(columns)


def _foreign_key_is_unique(property_: RelationshipProperty[object]) -> bool:
    """Prove a scalar relation is one-to-one from its FK uniqueness constraint."""

    columns = _foreign_key_columns(property_)
    if not columns or len({column.table for column in columns}) != 1:
        return False
    table = columns[0].table
    column_set = set(columns)
    for constraint in table.constraints:
        if (
            isinstance(constraint, PrimaryKeyConstraint | UniqueConstraint)
            and set(constraint.columns) == column_set
        ):
            return True
    return all(column.unique for column in columns)


def _kind(property_: RelationshipProperty[object]) -> RelationshipKind:
    direction = property_.direction.name
    if direction != "MANYTOMANY" and not property_.uselist and _foreign_key_is_unique(property_):
        return RelationshipKind.ONE_TO_ONE
    if direction == "MANYTOONE":
        return RelationshipKind.MANY_TO_ONE
    if direction == "ONETOMANY":
        return RelationshipKind.ONE_TO_MANY
    if direction == "MANYTOMANY":
        return RelationshipKind.MANY_TO_MANY
    raise ValueError("unsupported_direction")


def _cardinality(property_: RelationshipProperty[object]) -> RelationshipCardinality:
    return RelationshipCardinality.TO_MANY if property_.uselist else RelationshipCardinality.TO_ONE


def _nullable(property_: RelationshipProperty[object]) -> bool:
    """Return whether this mapper-side relationship may be absent.

    A unique child FK proves scalar cardinality in both directions, but only
    the MANYTOONE property owns that FK.  Its reverse scalar ONETOMANY view
    can still be absent because no database constraint requires every parent
    row to have a child row.
    """

    if property_.uselist:
        return True
    if property_.direction.name != "MANYTOONE":
        return True
    columns = tuple(property_.local_columns)
    return not columns or all(column.nullable for column in columns)


def _association_metadata(
    property_: RelationshipProperty[object],
) -> tuple[bool, tuple[str, ...], str | None]:
    if property_.direction.name != "ONETOMANY" or property_.secondary is not None:
        return False, (), None
    target_mapper = property_.mapper
    parent_mapper = property_.parent
    backlinks = [
        candidate
        for candidate in target_mapper.relationships
        if candidate.direction.name == "MANYTOONE" and candidate.mapper is parent_mapper
    ]
    targets = [
        candidate
        for candidate in target_mapper.relationships
        if candidate.direction.name == "MANYTOONE" and candidate.mapper is not parent_mapper
    ]
    if len(backlinks) != 1 or len(targets) != 1:
        return False, (), None
    scalar_fields = tuple(
        attribute.key
        for attribute in target_mapper.column_attrs
        if all(
            not column.primary_key
            and not column.foreign_keys
            and column.server_default is None
            and column.server_onupdate is None
            and column.computed is None
            for column in attribute.columns
        )
    )
    return True, scalar_fields, targets[0].key


def _ordering_position_field(property_: RelationshipProperty[object]) -> str | None:
    """Return only the narrow v1 writable ordering shape.

    SQLAlchemy accepts arbitrary expressions here.  Reordering may only write
    a single direct, ascending mapped target column; anything else stays
    display-ordered but is deliberately not a persistence contract.
    """

    if property_.direction.name != "ONETOMANY" or property_.secondary is not None:
        return None
    order_by = property_.order_by
    if not isinstance(order_by, tuple | list) or len(order_by) != 1:
        return None
    expression = order_by[0]
    if not isinstance(expression, Column) or expression.table is not property_.mapper.local_table:
        return None
    return expression.key


def inspect_relationships(model: type[object]) -> dict[str, RelationshipMetadata]:
    """Translate mapper relationships into backend-neutral structural facts."""

    mapper = inspect(model)
    assert mapper is not None
    metadata: dict[str, RelationshipMetadata] = {}
    for property_ in mapper.relationships:
        eligible, association_fields, association_target = _association_metadata(property_)
        position_field = _ordering_position_field(property_)
        metadata[property_.key] = RelationshipMetadata(
            relationship_id=property_.key,
            kind=_kind(property_),
            cardinality=_cardinality(property_),
            nullable=_nullable(property_),
            ordered=property_.order_by not in (False, None),
            reorderable=position_field is not None,
            ordering_position_field=position_field,
            self_referential=property_.mapper is mapper,
            view_only=property_.viewonly,
            has_secondary=property_.secondary is not None,
            cascade_delete="delete" in property_.cascade,
            delete_orphan="delete-orphan" in property_.cascade,
            association_object_eligible=eligible,
            association_scalar_fields=association_fields,
            association_target_relationship_id=association_target,
        )
    return metadata


def validate_relationship_definition(
    definition: RelationshipDefinition,
    *,
    source_model: type[object],
    target_model: type[object],
    association_target_model: type[object] | None = None,
) -> None:
    metadata = inspect_relationships(source_model).get(definition.relationship_id)
    if metadata is None:
        raise _invalid_relationship(definition, "mapper_relationship_not_found")
    mapper = inspect(source_model)
    assert mapper is not None
    property_ = mapper.relationships[definition.relationship_id]
    if property_.mapper.class_ is not target_model:
        raise _invalid_relationship(definition, "target_resource_mismatch")
    if definition.kind is RelationshipKind.ASSOCIATION_OBJECT:
        if not metadata.association_object_eligible:
            raise _invalid_relationship(definition, "association_object_unsupported")
        if definition.cardinality is not RelationshipCardinality.TO_MANY:
            raise _invalid_relationship(definition, "association_object_cardinality_invalid")
        if not set(definition.association_fields) <= set(metadata.association_scalar_fields):
            raise _invalid_relationship(definition, "association_fields_not_declared_by_mapper")
        assert metadata.association_target_relationship_id is not None
        association_target = mapper.relationships[definition.relationship_id].mapper.relationships[
            metadata.association_target_relationship_id
        ]
        if (
            association_target_model is None
            or association_target.mapper.class_ is not association_target_model
        ):
            raise _invalid_relationship(definition, "association_target_resource_mismatch")
    elif definition.kind is not metadata.kind:
        raise _invalid_relationship(definition, "kind_mismatch")
    if definition.cardinality is not metadata.cardinality:
        raise _invalid_relationship(definition, "cardinality_mismatch")
    if definition.effective_writable and metadata.view_only:
        raise _invalid_relationship(definition, "viewonly_relationship_not_writable")
    if definition.effective_writable and property_.lazy in {"dynamic", "write_only"}:
        raise _invalid_relationship(definition, "loader_strategy_not_writable")
    if definition.ordering is not None:
        field = definition.ordering.position_field
        if (
            definition.kind is not RelationshipKind.ONE_TO_MANY
            or metadata.ordering_position_field != field
            or property_.secondary is not None
        ):
            raise _invalid_relationship(definition, "ordering_persistence_unsupported")
        attribute = property_.mapper.column_attrs.get(field)
        if attribute is None or len(attribute.columns) != 1:
            raise _invalid_relationship(definition, "ordering_position_field_invalid")
        column = attribute.columns[0]
        if (
            not isinstance(column.type, Integer)
            or column.nullable
            or column.primary_key
            or bool(column.foreign_keys)
            or column.server_default is not None
            or column.server_onupdate is not None
            or column.computed is not None
        ):
            raise _invalid_relationship(definition, "ordering_position_field_unsafe")
    if definition.kind is RelationshipKind.MANY_TO_MANY and not metadata.has_secondary:
        raise _invalid_relationship(definition, "secondary_mapping_required")
    if definition.destructive_policy.allow_delete_orphan and not metadata.delete_orphan:
        raise _invalid_relationship(definition, "delete_orphan_not_mapper_supported")
    if definition.destructive_policy.allow_destructive_cascade and not metadata.cascade_delete:
        raise _invalid_relationship(definition, "delete_cascade_not_mapper_supported")


def _invalid_relationship(definition: RelationshipDefinition, reason: str) -> RakitError:
    return RakitError(
        code=ErrorCode.CONFIG_INVALID,
        message="Unsupported SQLAlchemy relationship configuration.",
        status_code=500,
        details={"relationship_id": definition.relationship_id, "reason": reason},
    )
