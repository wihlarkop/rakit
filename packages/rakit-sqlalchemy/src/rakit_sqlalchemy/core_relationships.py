from __future__ import annotations

from dataclasses import dataclass

from rakit_core.errors import ErrorCode, RakitError
from rakit_core.relationships import (
    RelationshipCardinality,
    RelationshipDefinition,
    RelationshipKind,
    RelationshipMetadata,
)
from sqlalchemy import Column, Integer, Table
from sqlalchemy.schema import PrimaryKeyConstraint, UniqueConstraint


@dataclass(frozen=True, slots=True)
class SQLAlchemyCoreRelationshipBinding:
    """Explicit physical binding for a Core relationship when schema paths are ambiguous."""

    foreign_key_field: str | None = None
    secondary_table: Table | None = None
    secondary_source_field: str | None = None
    secondary_target_field: str | None = None
    association_target_field: str | None = None


@dataclass(frozen=True, slots=True)
class ResolvedCoreRelationship:
    """Adapter-private physical relation used by Core read and mutation services."""

    metadata: RelationshipMetadata
    source_table: Table
    target_table: Table
    foreign_key_field: str | None = None
    foreign_key_on_source: bool = False
    secondary_table: Table | None = None
    secondary_source_field: str | None = None
    secondary_target_field: str | None = None
    association_target_table: Table | None = None
    association_target_field: str | None = None


def _invalid(definition: RelationshipDefinition, reason: str) -> RakitError:
    return RakitError(
        code=ErrorCode.CONFIG_INVALID,
        message="Unsupported SQLAlchemy Core relationship configuration.",
        status_code=500,
        details={"relationship_id": definition.relationship_id, "reason": reason},
    )


def _column_is_unique(column: Column[object]) -> bool:
    if column.primary_key or column.unique:
        return True
    for constraint in column.table.constraints:
        if isinstance(constraint, PrimaryKeyConstraint | UniqueConstraint) and set(
            constraint.columns
        ) == {column}:
            return True
    return False


def _foreign_key_edges(source: Table, target: Table) -> tuple[Column[object], ...]:
    return tuple(
        column
        for column in source.columns
        if any(foreign_key.column.table is target for foreign_key in column.foreign_keys)
    )


def _choose_edge(
    definition: RelationshipDefinition,
    edges: tuple[Column[object], ...],
    *,
    explicit_field: str | None,
    missing_reason: str,
    ambiguous_reason: str,
) -> Column[object]:
    if explicit_field is not None:
        matches = tuple(column for column in edges if column.key == explicit_field)
        if len(matches) != 1:
            raise _invalid(definition, "explicit_foreign_key_binding_invalid")
        return matches[0]
    if not edges:
        raise _invalid(definition, missing_reason)
    if len(edges) != 1:
        raise _invalid(definition, ambiguous_reason)
    return edges[0]


def _cascade_delete(column: Column[object]) -> bool:
    return any(
        isinstance(foreign_key.ondelete, str) and foreign_key.ondelete.upper() == "CASCADE"
        for foreign_key in column.foreign_keys
    )


def _association_scalar_fields(table: Table) -> tuple[str, ...]:
    return tuple(
        column.key
        for column in table.columns
        if not column.primary_key
        and not column.foreign_keys
        and column.computed is None
        and column.server_default is None
        and column.server_onupdate is None
    )


def _ordering_position_field(
    definition: RelationshipDefinition,
    *,
    target_table: Table,
) -> str | None:
    ordering = definition.ordering
    if ordering is None:
        return None
    if definition.kind not in {RelationshipKind.ONE_TO_MANY, RelationshipKind.ASSOCIATION_OBJECT}:
        raise _invalid(definition, "ordering_persistence_unsupported")
    if ordering.position_field not in target_table.c:
        raise _invalid(definition, "ordering_position_field_invalid")
    column = target_table.c[ordering.position_field]
    if (
        not isinstance(column.type, Integer)
        or column.nullable
        or column.primary_key
        or bool(column.foreign_keys)
        or column.server_default is not None
        or column.server_onupdate is not None
        or column.computed is not None
    ):
        raise _invalid(definition, "ordering_position_field_unsafe")
    return column.key


def _direct_relationship(
    definition: RelationshipDefinition,
    *,
    source_table: Table,
    target_table: Table,
    binding: SQLAlchemyCoreRelationshipBinding | None,
) -> ResolvedCoreRelationship:
    explicit_field = binding.foreign_key_field if binding is not None else None
    source_edges = _foreign_key_edges(source_table, target_table)
    target_edges = _foreign_key_edges(target_table, source_table)

    if definition.kind is RelationshipKind.MANY_TO_ONE:
        column = _choose_edge(
            definition,
            source_edges,
            explicit_field=explicit_field,
            missing_reason="foreign_key_path_not_found",
            ambiguous_reason="foreign_key_path_ambiguous",
        )
        if definition.cardinality is not RelationshipCardinality.TO_ONE:
            raise _invalid(definition, "cardinality_mismatch")
        nullable = bool(column.nullable)
        if definition.nullable != nullable:
            raise _invalid(definition, "nullable_mismatch")
        position_field = _ordering_position_field(definition, target_table=target_table)
        metadata = RelationshipMetadata(
            relationship_id=definition.relationship_id,
            kind=definition.kind,
            cardinality=definition.cardinality,
            nullable=nullable,
            ordered=position_field is not None,
            reorderable=position_field is not None,
            ordering_position_field=position_field,
            self_referential=source_table is target_table,
            view_only=False,
            has_secondary=False,
            cascade_delete=_cascade_delete(column),
            delete_orphan=False,
        )
        return ResolvedCoreRelationship(
            metadata=metadata,
            source_table=source_table,
            target_table=target_table,
            foreign_key_field=column.key,
            foreign_key_on_source=True,
        )

    if definition.kind is RelationshipKind.ONE_TO_MANY:
        column = _choose_edge(
            definition,
            target_edges,
            explicit_field=explicit_field,
            missing_reason="foreign_key_path_not_found",
            ambiguous_reason="foreign_key_path_ambiguous",
        )
        if definition.cardinality is not RelationshipCardinality.TO_MANY:
            raise _invalid(definition, "cardinality_mismatch")
        position_field = _ordering_position_field(definition, target_table=target_table)
        metadata = RelationshipMetadata(
            relationship_id=definition.relationship_id,
            kind=definition.kind,
            cardinality=definition.cardinality,
            nullable=True,
            ordered=position_field is not None,
            reorderable=position_field is not None,
            ordering_position_field=position_field,
            self_referential=source_table is target_table,
            view_only=False,
            has_secondary=False,
            cascade_delete=_cascade_delete(column),
            delete_orphan=False,
        )
        return ResolvedCoreRelationship(
            metadata=metadata,
            source_table=source_table,
            target_table=target_table,
            foreign_key_field=column.key,
            foreign_key_on_source=False,
        )

    if definition.kind is RelationshipKind.ONE_TO_ONE:
        candidates = tuple(
            (column, True) for column in source_edges if _column_is_unique(column)
        ) + tuple((column, False) for column in target_edges if _column_is_unique(column))
        if explicit_field is not None:
            candidates = tuple(item for item in candidates if item[0].key == explicit_field)
        if not candidates:
            raise _invalid(definition, "one_to_one_unique_path_not_found")
        if len(candidates) != 1:
            raise _invalid(definition, "one_to_one_path_ambiguous")
        column, on_source = candidates[0]
        if definition.cardinality is not RelationshipCardinality.TO_ONE:
            raise _invalid(definition, "cardinality_mismatch")
        nullable = bool(column.nullable) if on_source else True
        if definition.nullable != nullable:
            raise _invalid(definition, "nullable_mismatch")
        position_field = _ordering_position_field(definition, target_table=target_table)
        metadata = RelationshipMetadata(
            relationship_id=definition.relationship_id,
            kind=definition.kind,
            cardinality=definition.cardinality,
            nullable=nullable,
            ordered=position_field is not None,
            reorderable=position_field is not None,
            ordering_position_field=position_field,
            self_referential=source_table is target_table,
            view_only=False,
            has_secondary=False,
            cascade_delete=_cascade_delete(column),
            delete_orphan=False,
        )
        return ResolvedCoreRelationship(
            metadata=metadata,
            source_table=source_table,
            target_table=target_table,
            foreign_key_field=column.key,
            foreign_key_on_source=on_source,
        )

    raise _invalid(definition, "direct_relationship_kind_invalid")


def _secondary_candidate_tables(source_table: Table, target_table: Table) -> tuple[Table, ...]:
    if source_table.metadata is not target_table.metadata:
        return ()
    return tuple(
        table
        for table in source_table.metadata.tables.values()
        if table is not source_table
        and table is not target_table
        and _foreign_key_edges(table, source_table)
        and _foreign_key_edges(table, target_table)
    )


def _many_to_many_relationship(
    definition: RelationshipDefinition,
    *,
    source_table: Table,
    target_table: Table,
    binding: SQLAlchemyCoreRelationshipBinding | None,
) -> ResolvedCoreRelationship:
    if definition.cardinality is not RelationshipCardinality.TO_MANY:
        raise _invalid(definition, "cardinality_mismatch")
    explicit_secondary = binding.secondary_table if binding is not None else None
    if explicit_secondary is not None:
        candidates = (explicit_secondary,)
    else:
        candidates = _secondary_candidate_tables(source_table, target_table)
    if not candidates:
        raise _invalid(definition, "secondary_table_not_found")
    if len(candidates) != 1:
        raise _invalid(definition, "secondary_table_ambiguous")
    secondary = candidates[0]
    source_edge = _choose_edge(
        definition,
        _foreign_key_edges(secondary, source_table),
        explicit_field=binding.secondary_source_field if binding is not None else None,
        missing_reason="secondary_source_foreign_key_not_found",
        ambiguous_reason="secondary_source_foreign_key_ambiguous",
    )
    target_edge = _choose_edge(
        definition,
        _foreign_key_edges(secondary, target_table),
        explicit_field=binding.secondary_target_field if binding is not None else None,
        missing_reason="secondary_target_foreign_key_not_found",
        ambiguous_reason="secondary_target_foreign_key_ambiguous",
    )
    if definition.ordering is not None:
        raise _invalid(definition, "ordering_requires_explicit_association_resource")
    metadata = RelationshipMetadata(
        relationship_id=definition.relationship_id,
        kind=definition.kind,
        cardinality=definition.cardinality,
        nullable=True,
        ordered=False,
        reorderable=False,
        self_referential=source_table is target_table,
        view_only=False,
        has_secondary=True,
        cascade_delete=_cascade_delete(source_edge) or _cascade_delete(target_edge),
        delete_orphan=False,
    )
    return ResolvedCoreRelationship(
        metadata=metadata,
        source_table=source_table,
        target_table=target_table,
        secondary_table=secondary,
        secondary_source_field=source_edge.key,
        secondary_target_field=target_edge.key,
    )


def _association_relationship(
    definition: RelationshipDefinition,
    *,
    source_table: Table,
    association_table: Table,
    association_target_table: Table,
    binding: SQLAlchemyCoreRelationshipBinding | None,
) -> ResolvedCoreRelationship:
    if definition.cardinality is not RelationshipCardinality.TO_MANY:
        raise _invalid(definition, "association_object_cardinality_invalid")
    parent_edge = _choose_edge(
        definition,
        _foreign_key_edges(association_table, source_table),
        explicit_field=binding.foreign_key_field if binding is not None else None,
        missing_reason="association_parent_foreign_key_not_found",
        ambiguous_reason="association_parent_foreign_key_ambiguous",
    )
    target_edge = _choose_edge(
        definition,
        _foreign_key_edges(association_table, association_target_table),
        explicit_field=binding.association_target_field if binding is not None else None,
        missing_reason="association_target_foreign_key_not_found",
        ambiguous_reason="association_target_foreign_key_ambiguous",
    )
    scalar_fields = _association_scalar_fields(association_table)
    if not set(definition.association_fields) <= set(scalar_fields):
        raise _invalid(definition, "association_fields_not_declared_by_table")
    position_field = _ordering_position_field(definition, target_table=association_table)
    metadata = RelationshipMetadata(
        relationship_id=definition.relationship_id,
        kind=RelationshipKind.ASSOCIATION_OBJECT,
        cardinality=definition.cardinality,
        nullable=True,
        ordered=position_field is not None,
        reorderable=position_field is not None,
        ordering_position_field=position_field,
        self_referential=source_table is association_target_table,
        view_only=False,
        has_secondary=False,
        cascade_delete=_cascade_delete(parent_edge),
        delete_orphan=False,
        association_object_eligible=True,
        association_scalar_fields=scalar_fields,
        association_target_relationship_id=target_edge.key,
    )
    return ResolvedCoreRelationship(
        metadata=metadata,
        source_table=source_table,
        target_table=association_table,
        foreign_key_field=parent_edge.key,
        foreign_key_on_source=False,
        association_target_table=association_target_table,
        association_target_field=target_edge.key,
    )


def resolve_relationship_definition(
    definition: RelationshipDefinition,
    *,
    source_table: Table,
    target_table: Table,
    association_target_table: Table | None = None,
    binding: SQLAlchemyCoreRelationshipBinding | None = None,
) -> ResolvedCoreRelationship:
    """Resolve one declared neutral relationship against public Core schema metadata."""

    if definition.kind is RelationshipKind.MANY_TO_MANY:
        return _many_to_many_relationship(
            definition,
            source_table=source_table,
            target_table=target_table,
            binding=binding,
        )
    if definition.kind is RelationshipKind.ASSOCIATION_OBJECT:
        if association_target_table is None:
            raise _invalid(definition, "association_target_resource_missing")
        return _association_relationship(
            definition,
            source_table=source_table,
            association_table=target_table,
            association_target_table=association_target_table,
            binding=binding,
        )
    return _direct_relationship(
        definition,
        source_table=source_table,
        target_table=target_table,
        binding=binding,
    )


__all__ = [
    "ResolvedCoreRelationship",
    "SQLAlchemyCoreRelationshipBinding",
    "resolve_relationship_definition",
]
