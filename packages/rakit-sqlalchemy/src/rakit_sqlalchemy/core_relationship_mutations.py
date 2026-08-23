from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass

from rakit_core.concurrency import ConcurrencyTokenService, ConcurrencyVersionProvider
from rakit_core.errors import ErrorCode, RakitError
from rakit_core.identity import RecordIdentity, canonical_identity_payload
from rakit_core.pagination import PageResult
from rakit_core.relationship_mutations import (
    ClearRelated,
    CreateRelated,
    DeleteRelated,
    LinkRelated,
    RelationshipCandidate,
    RelationshipChangePlan,
    RelationshipEditorRow,
    RelationshipMutationResult,
    ReorderRelated,
    SetRelated,
    UnlinkRelated,
    UpdateAssociationRelated,
    UpdateRelated,
)
from rakit_core.relationships import (
    CompiledRelationship,
    RelationshipCardinality,
    RelationshipKind,
    resolve_record_label,
)
from sqlalchemy import delete as sa_delete
from sqlalchemy import insert as sa_insert
from sqlalchemy import select
from sqlalchemy import update as sa_update
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncConnection

from .core_datasource import SQLAlchemyCoreDataSource
from .core_relationships import ResolvedCoreRelationship
from .core_uow import SQLAlchemyCoreUnitOfWork


@dataclass(frozen=True, slots=True)
class _RelatedRow:
    target: dict[str, object]
    association: dict[str, object] | None = None


class SQLAlchemyCoreRelationshipMutationService:
    """Execute compiled relationship graph steps with SQLAlchemy Core only.

    The service owns no transaction. Mutation methods require the already-open
    ``SQLAlchemyCoreUnitOfWork`` and use its ``AsyncConnection`` for every
    scoped read and write. Read/editor helpers open short-lived read-only
    connections from the same adapter engine.
    """

    def __init__(
        self,
        *,
        parent_data_source: SQLAlchemyCoreDataSource,
        relationships: tuple[CompiledRelationship, ...],
        target_data_sources: Mapping[str, SQLAlchemyCoreDataSource],
        concurrency_provider: ConcurrencyVersionProvider,
        concurrency_tokens: ConcurrencyTokenService,
    ) -> None:
        self._parent_data_source = parent_data_source
        self._relationships = {
            str(entry.definition.relationship_id): entry for entry in relationships
        }
        self._target_data_sources = dict(target_data_sources)
        self._concurrency_provider = concurrency_provider
        self._concurrency_tokens = concurrency_tokens
        for entry in relationships:
            if self._target_resource_id(entry) not in self._target_data_sources:
                raise ValueError("Every Core relationship requires its target data source")

    @staticmethod
    def _identity_key(identity: RecordIdentity) -> str:
        return json.dumps(
            canonical_identity_payload(identity), sort_keys=True, separators=(",", ":")
        )

    @staticmethod
    def _token_resource_id(entry: CompiledRelationship) -> str:
        return f"{entry.source_resource_id}:relationship:{entry.definition.relationship_id}"

    @staticmethod
    def _conflict(message: str = "Relationship state changed before the mutation.") -> RakitError:
        return RakitError(
            code=ErrorCode.RESOURCE_CONFLICT,
            message=message,
            status_code=409,
        )

    @staticmethod
    def _not_found() -> RakitError:
        return RakitError(
            code=ErrorCode.RESOURCE_NOT_FOUND,
            message="Relationship record not found.",
            status_code=404,
        )

    @staticmethod
    def _configuration(reason: str, message: str) -> RakitError:
        return RakitError(
            code=ErrorCode.CONFIG_INVALID,
            message=message,
            status_code=500,
            details={"reason": reason},
        )

    def _entry(self, relationship_id: str) -> CompiledRelationship:
        try:
            return self._relationships[relationship_id]
        except KeyError as exc:
            raise self._configuration(
                "relationship_not_compiled",
                "Relationship is not compiled for this SQLAlchemy Core resource.",
            ) from exc

    @staticmethod
    def _target_resource_id(entry: CompiledRelationship) -> str:
        if entry.definition.kind is RelationshipKind.ASSOCIATION_OBJECT:
            assert entry.definition.association_target_resource_id is not None
            return str(entry.definition.association_target_resource_id)
        return str(entry.definition.target_resource_id)

    def _target_source(self, entry: CompiledRelationship) -> SQLAlchemyCoreDataSource:
        return self._target_data_sources[self._target_resource_id(entry)]

    def _resolved(self, entry: CompiledRelationship) -> ResolvedCoreRelationship:
        return self._parent_data_source.resolved_relationship(str(entry.definition.relationship_id))

    @staticmethod
    def _identity_value(data_source: SQLAlchemyCoreDataSource, identity: RecordIdentity) -> object:
        field = data_source.identity_fields[0]
        if set(identity.values) != {field}:
            raise SQLAlchemyCoreRelationshipMutationService._configuration(
                "relationship_identity_invalid",
                "Relationship identity does not match its SQLAlchemy Core resource.",
            )
        return identity.values[field]

    @staticmethod
    def _mapping_from_subquery(
        row: Mapping[str, object], field_names: tuple[str, ...]
    ) -> dict[str, object]:
        return {field: row[field] for field in field_names}

    async def _parent(
        self, connection: AsyncConnection, identity: RecordIdentity
    ) -> dict[str, object]:
        parent = await self._parent_data_source.resolve_scoped(connection, identity)
        if parent is None:
            raise self._not_found()
        return parent

    async def _related_rows(
        self,
        connection: AsyncConnection,
        parent_identity: RecordIdentity,
        entry: CompiledRelationship,
    ) -> tuple[_RelatedRow, ...]:
        resolved = self._resolved(entry)
        target_source = self._target_source(entry)
        target_scope = target_source.scoped_statement().subquery()
        target_identity_field = target_source.identity_fields[0]
        parent_value = self._identity_value(self._parent_data_source, parent_identity)
        kind = entry.definition.kind

        if kind in {RelationshipKind.MANY_TO_ONE, RelationshipKind.ONE_TO_ONE} and (
            resolved.foreign_key_on_source
        ):
            parent = await self._parent(connection, parent_identity)
            assert resolved.foreign_key_field is not None
            target_value = parent.get(resolved.foreign_key_field)
            if target_value is None:
                return ()
            result = await connection.execute(
                select(target_scope).where(target_scope.c[target_identity_field] == target_value)
            )
            row = result.mappings().one_or_none()
            if row is None:
                return ()
            return (_RelatedRow(self._mapping_from_subquery(row, target_source.fields)),)

        if kind in {RelationshipKind.ONE_TO_MANY, RelationshipKind.ONE_TO_ONE}:
            assert resolved.foreign_key_field is not None
            statement = select(target_scope).where(
                target_scope.c[resolved.foreign_key_field] == parent_value
            )
            result = await connection.execute(statement)
            return tuple(
                _RelatedRow(self._mapping_from_subquery(row, target_source.fields))
                for row in result.mappings().all()
            )

        if kind is RelationshipKind.MANY_TO_MANY:
            secondary = resolved.secondary_table
            source_field = resolved.secondary_source_field
            target_field = resolved.secondary_target_field
            assert secondary is not None and source_field is not None and target_field is not None
            statement = (
                select(target_scope)
                .select_from(
                    target_scope.join(
                        secondary,
                        target_scope.c[target_identity_field] == secondary.c[target_field],
                    )
                )
                .where(secondary.c[source_field] == parent_value)
            )
            result = await connection.execute(statement)
            return tuple(
                _RelatedRow(self._mapping_from_subquery(row, target_source.fields))
                for row in result.mappings().all()
            )

        if kind is RelationshipKind.ASSOCIATION_OBJECT:
            association = resolved.target_table
            parent_field = resolved.foreign_key_field
            target_field = resolved.association_target_field
            assert parent_field is not None and target_field is not None
            association_alias = association.alias("rakit_association")
            statement = (
                select(target_scope, association_alias)
                .select_from(
                    target_scope.join(
                        association_alias,
                        target_scope.c[target_identity_field] == association_alias.c[target_field],
                    )
                )
                .where(association_alias.c[parent_field] == parent_value)
            )
            result = await connection.execute(statement)
            association_fields = tuple(column.key for column in association.columns)
            rows: list[_RelatedRow] = []
            for row in result.mappings().all():
                rows.append(
                    _RelatedRow(
                        target=self._mapping_from_subquery(row, target_source.fields),
                        association={
                            field: row[f"rakit_association_{field}"] for field in association_fields
                        },
                    )
                )
            return tuple(rows)

        raise self._configuration(
            "relationship_kind_unsupported",
            "SQLAlchemy Core relationship kind is not supported at runtime.",
        )

    async def _state_digest(
        self,
        connection: AsyncConnection,
        parent_identity: RecordIdentity,
        entry: CompiledRelationship,
    ) -> str:
        rows = await self._related_rows(connection, parent_identity, entry)
        target_source = self._target_source(entry)
        payload = []
        for row in rows:
            target_identity = target_source.identity_for(row.target)
            item: dict[str, object] = {
                "identity": canonical_identity_payload(target_identity),
            }
            if row.association is not None:
                item["association"] = {
                    field: row.association.get(field)
                    for field in entry.definition.association_fields
                }
                if entry.ordering is not None:
                    field = str(entry.ordering.position_field)
                    item["position"] = row.association.get(field)
            elif entry.ordering is not None:
                field = str(entry.ordering.position_field)
                item["position"] = row.target.get(field)
            payload.append(item)
        encoded = json.dumps(
            sorted(payload, key=lambda value: json.dumps(value["identity"], sort_keys=True)),
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        )
        return hashlib.sha256(encoded.encode("utf-8")).hexdigest()

    async def issue_concurrency_token(
        self, parent_identity: RecordIdentity, relationship_id: str
    ) -> str:
        entry = self._entry(relationship_id)
        async with self._parent_data_source._engine.connect() as connection:
            parent = await self._parent(connection, parent_identity)
            digest = await self._state_digest(connection, parent_identity, entry)
        return self._concurrency_tokens.issue(
            self._token_resource_id(entry),
            parent_identity,
            self._concurrency_provider.version_for(parent),
            base_snapshot={
                "relationship_id": relationship_id,
                "relationship_state_digest": digest,
            },
        )

    async def editor_page(
        self,
        parent_identity: RecordIdentity,
        relationship_id: str,
        *,
        child_fields: tuple[str, ...] = (),
        page: int = 1,
        per_page: int = 25,
    ) -> PageResult[RelationshipEditorRow]:
        if page < 1 or per_page < 1 or per_page > 200:
            raise RakitError(
                code=ErrorCode.VALIDATION_FAILED,
                message="Invalid relationship page.",
                status_code=422,
            )
        entry = self._entry(relationship_id)
        target_source = self._target_source(entry)
        if not set(child_fields) <= set(target_source.fields):
            raise self._configuration(
                "relationship_child_field_unknown",
                "Relationship editor requested an unknown child field.",
            )
        async with self._parent_data_source._engine.connect() as connection:
            await self._parent(connection, parent_identity)
            rows = await self._related_rows(connection, parent_identity, entry)
        start = (page - 1) * per_page
        selected = rows[start : start + per_page + 1]
        has_next = len(selected) > per_page
        selected = selected[:per_page]
        editor_rows = []
        association_source = None
        if entry.definition.kind is RelationshipKind.ASSOCIATION_OBJECT:
            association_source = self._target_data_sources.get(
                str(entry.definition.target_resource_id)
            )
        for row in selected:
            candidate_identity = target_source.identity_for(row.target)
            association_identity = None
            values = {field: row.target[field] for field in child_fields}
            if row.association is not None:
                values.update(
                    {field: row.association[field] for field in entry.definition.association_fields}
                )
                if association_source is not None:
                    association_identity = association_source.identity_for(row.association)
            editor_rows.append(
                RelationshipEditorRow(
                    candidate=RelationshipCandidate(
                        identity=candidate_identity,
                        label=resolve_record_label(entry.definition, row.target),
                    ),
                    values=values,
                    association_identity=association_identity,
                )
            )
        return PageResult(
            items=tuple(editor_rows),
            page=page,
            per_page=per_page,
            has_previous=page > 1,
            has_next=has_next,
            total_count=None,
        )

    async def reorder_identities(
        self,
        parent_identity: RecordIdentity,
        relationship_id: str,
        *,
        maximum: int,
    ) -> tuple[RecordIdentity, ...] | None:
        entry = self._entry(relationship_id)
        if maximum < 1 or entry.ordering is None:
            return None
        async with self._parent_data_source._engine.connect() as connection:
            rows = await self._related_rows(connection, parent_identity, entry)
        if len(rows) > maximum:
            return None
        target_source = self._target_source(entry)
        position_field = str(entry.ordering.position_field)
        ordered = sorted(
            rows,
            key=lambda row: (
                (row.association or row.target).get(position_field),
                self._identity_key(target_source.identity_for(row.target)),
            ),
        )
        return tuple(target_source.identity_for(row.target) for row in ordered)

    async def _resolve_targets(
        self,
        connection: AsyncConnection,
        entry: CompiledRelationship,
        identities: tuple[RecordIdentity, ...],
    ) -> dict[str, dict[str, object]]:
        target_source = self._target_source(entry)
        targets: dict[str, dict[str, object]] = {}
        for identity in identities:
            record = await target_source.resolve_scoped(connection, identity)
            if record is None:
                raise self._not_found()
            targets[self._identity_key(identity)] = record
        return targets

    def _require_sane_rowcount(self, result: CursorResult[object]) -> int:
        if not result.supports_sane_rowcount():
            raise self._configuration(
                "relationship_rowcount_not_sane",
                "SQLAlchemy Core relationship mutation requires sane rowcount semantics.",
            )
        rowcount = result.rowcount
        if rowcount is None or rowcount < 0:
            raise self._configuration(
                "relationship_rowcount_unavailable",
                "SQLAlchemy Core relationship mutation could not observe matched rows.",
            )
        return rowcount

    async def _verify_and_claim_parent(
        self,
        connection: AsyncConnection,
        parent_identity: RecordIdentity,
        parent: dict[str, object],
        entry: CompiledRelationship,
        change: RelationshipChangePlan,
    ) -> None:
        token = change.concurrency_token
        if token is None:
            raise self._conflict("A relationship concurrency token is required.")
        version = self._concurrency_provider.version_for(parent)
        self._concurrency_tokens.verify(
            token,
            self._token_resource_id(entry),
            parent_identity,
            version,
        )
        base = self._concurrency_tokens.base_snapshot(
            token, self._token_resource_id(entry), parent_identity
        )
        if base.get("relationship_id") != change.relationship_id:
            raise self._conflict("Relationship token does not match this relationship.")
        digest = await self._state_digest(connection, parent_identity, entry)
        if base.get("relationship_state_digest") != digest:
            raise self._conflict()

        predicate_values = dict(self._concurrency_provider.predicate_values_for(parent))
        next_values = dict(self._concurrency_provider.next_values_for(parent))
        unknown = (set(predicate_values) | set(next_values)).difference(
            self._parent_data_source.fields
        )
        if unknown:
            raise self._configuration(
                "relationship_concurrency_field_unknown",
                "Relationship concurrency provider referenced an unknown parent field.",
            )
        statement = sa_update(self._parent_data_source._table).where(
            *self._parent_data_source.identity_conditions(parent_identity),
            *(
                self._parent_data_source._table.c[field] == value
                for field, value in predicate_values.items()
            ),
        )
        if next_values:
            statement = statement.values(**next_values)
        result = await connection.execute(statement)
        if self._require_sane_rowcount(result) != 1:
            raise self._conflict()

    async def _set_to_one(
        self,
        connection: AsyncConnection,
        parent_identity: RecordIdentity,
        entry: CompiledRelationship,
        target_identity: RecordIdentity,
    ) -> None:
        resolved = self._resolved(entry)
        target_source = self._target_source(entry)
        target_value = self._identity_value(target_source, target_identity)
        parent_value = self._identity_value(self._parent_data_source, parent_identity)
        assert resolved.foreign_key_field is not None
        if resolved.foreign_key_on_source:
            result = await connection.execute(
                sa_update(self._parent_data_source._table)
                .where(*self._parent_data_source.identity_conditions(parent_identity))
                .values({resolved.foreign_key_field: target_value})
            )
            if self._require_sane_rowcount(result) != 1:
                raise self._not_found()
            return

        target_table = target_source._table
        if entry.definition.kind is RelationshipKind.ONE_TO_ONE:
            current = await self._related_rows(connection, parent_identity, entry)
            if current:
                if not target_table.c[resolved.foreign_key_field].nullable:
                    current_identity = target_source.identity_for(current[0].target)
                    if self._identity_key(current_identity) != self._identity_key(target_identity):
                        raise self._configuration(
                            "one_to_one_replacement_requires_nullable_foreign_key",
                            "Replacing this one-to-one relationship requires a nullable child FK.",
                        )
                else:
                    await connection.execute(
                        sa_update(target_table)
                        .where(target_table.c[resolved.foreign_key_field] == parent_value)
                        .values({resolved.foreign_key_field: None})
                    )
        result = await connection.execute(
            sa_update(target_table)
            .where(*target_source.identity_conditions(target_identity))
            .values({resolved.foreign_key_field: parent_value})
        )
        if self._require_sane_rowcount(result) != 1:
            raise self._not_found()

    async def _clear_to_one(
        self,
        connection: AsyncConnection,
        parent_identity: RecordIdentity,
        entry: CompiledRelationship,
    ) -> None:
        if not entry.definition.nullable:
            raise self._configuration(
                "relationship_not_nullable",
                "This SQLAlchemy Core relationship cannot be cleared.",
            )
        resolved = self._resolved(entry)
        assert resolved.foreign_key_field is not None
        if resolved.foreign_key_on_source:
            await connection.execute(
                sa_update(self._parent_data_source._table)
                .where(*self._parent_data_source.identity_conditions(parent_identity))
                .values({resolved.foreign_key_field: None})
            )
            return
        parent_value = self._identity_value(self._parent_data_source, parent_identity)
        target_table = self._target_source(entry)._table
        await connection.execute(
            sa_update(target_table)
            .where(target_table.c[resolved.foreign_key_field] == parent_value)
            .values({resolved.foreign_key_field: None})
        )

    async def _link_many(
        self,
        connection: AsyncConnection,
        parent_identity: RecordIdentity,
        entry: CompiledRelationship,
        target_identity: RecordIdentity,
    ) -> None:
        resolved = self._resolved(entry)
        target_source = self._target_source(entry)
        parent_value = self._identity_value(self._parent_data_source, parent_identity)
        target_value = self._identity_value(target_source, target_identity)
        if entry.definition.kind is RelationshipKind.ONE_TO_MANY:
            assert resolved.foreign_key_field is not None
            result = await connection.execute(
                sa_update(target_source._table)
                .where(*target_source.identity_conditions(target_identity))
                .values({resolved.foreign_key_field: parent_value})
            )
            if self._require_sane_rowcount(result) != 1:
                raise self._not_found()
            return
        if entry.definition.kind is RelationshipKind.MANY_TO_MANY:
            secondary = resolved.secondary_table
            source_field = resolved.secondary_source_field
            target_field = resolved.secondary_target_field
            assert secondary is not None and source_field is not None and target_field is not None
            current = await connection.scalar(
                select(secondary.c[source_field]).where(
                    secondary.c[source_field] == parent_value,
                    secondary.c[target_field] == target_value,
                )
            )
            if current is None:
                await connection.execute(
                    sa_insert(secondary).values(
                        {source_field: parent_value, target_field: target_value}
                    )
                )
            return
        if entry.definition.kind is RelationshipKind.ASSOCIATION_OBJECT:
            association = resolved.target_table
            parent_field = resolved.foreign_key_field
            target_field = resolved.association_target_field
            assert parent_field is not None and target_field is not None
            existing = await connection.scalar(
                select(association.c[parent_field]).where(
                    association.c[parent_field] == parent_value,
                    association.c[target_field] == target_value,
                )
            )
            if existing is None:
                required_scalars = tuple(
                    column.key
                    for column in association.columns
                    if not column.primary_key
                    and not column.foreign_keys
                    and not column.nullable
                    and column.default is None
                    and column.server_default is None
                )
                if required_scalars:
                    raise self._configuration(
                        "association_link_requires_scalar_values",
                        "Association link requires explicit scalar values through child creation.",
                    )
                await connection.execute(
                    sa_insert(association).values(
                        {parent_field: parent_value, target_field: target_value}
                    )
                )
            return
        raise self._configuration(
            "relationship_link_kind_invalid",
            "Relationship does not support collection linking.",
        )

    async def _unlink_many(
        self,
        connection: AsyncConnection,
        parent_identity: RecordIdentity,
        entry: CompiledRelationship,
        target_identity: RecordIdentity,
    ) -> None:
        resolved = self._resolved(entry)
        target_source = self._target_source(entry)
        parent_value = self._identity_value(self._parent_data_source, parent_identity)
        target_value = self._identity_value(target_source, target_identity)
        if entry.definition.kind is RelationshipKind.ONE_TO_MANY:
            assert resolved.foreign_key_field is not None
            column = target_source._table.c[resolved.foreign_key_field]
            if not column.nullable:
                raise self._configuration(
                    "relationship_unlink_requires_nullable_foreign_key",
                    "Unlinking this child requires a nullable foreign key.",
                )
            await connection.execute(
                sa_update(target_source._table)
                .where(
                    *target_source.identity_conditions(target_identity),
                    column == parent_value,
                )
                .values({resolved.foreign_key_field: None})
            )
            return
        if entry.definition.kind is RelationshipKind.MANY_TO_MANY:
            secondary = resolved.secondary_table
            source_field = resolved.secondary_source_field
            target_field = resolved.secondary_target_field
            assert secondary is not None and source_field is not None and target_field is not None
            await connection.execute(
                sa_delete(secondary).where(
                    secondary.c[source_field] == parent_value,
                    secondary.c[target_field] == target_value,
                )
            )
            return
        if entry.definition.kind is RelationshipKind.ASSOCIATION_OBJECT:
            association = resolved.target_table
            parent_field = resolved.foreign_key_field
            target_field = resolved.association_target_field
            assert parent_field is not None and target_field is not None
            await connection.execute(
                sa_delete(association).where(
                    association.c[parent_field] == parent_value,
                    association.c[target_field] == target_value,
                )
            )
            return
        raise self._configuration(
            "relationship_unlink_kind_invalid",
            "Relationship does not support collection unlinking.",
        )

    async def _update_association(
        self,
        connection: AsyncConnection,
        parent_identity: RecordIdentity,
        entry: CompiledRelationship,
        step: UpdateAssociationRelated,
    ) -> None:
        if entry.definition.kind is not RelationshipKind.ASSOCIATION_OBJECT:
            raise self._configuration(
                "association_update_kind_invalid",
                "Association scalar updates require an association-object relationship.",
            )
        if not set(step.values) <= set(entry.definition.association_fields):
            raise self._configuration(
                "association_update_field_invalid",
                "Association update contains fields outside the compiled allow-list.",
            )
        resolved = self._resolved(entry)
        association_source = self._target_data_sources.get(str(entry.definition.target_resource_id))
        association = resolved.target_table
        conditions = []
        if step.association_identity is not None and association_source is not None:
            conditions.extend(association_source.identity_conditions(step.association_identity))
        else:
            parent_field = resolved.foreign_key_field
            target_field = resolved.association_target_field
            assert parent_field is not None and target_field is not None
            conditions.extend(
                (
                    association.c[parent_field]
                    == self._identity_value(self._parent_data_source, parent_identity),
                    association.c[target_field]
                    == self._identity_value(self._target_source(entry), step.target_identity),
                )
            )
        result = await connection.execute(
            sa_update(association).where(*conditions).values(**dict(step.values))
        )
        if self._require_sane_rowcount(result) != 1:
            raise self._not_found()

    async def _reorder(
        self,
        connection: AsyncConnection,
        parent_identity: RecordIdentity,
        entry: CompiledRelationship,
        step: ReorderRelated,
    ) -> None:
        if entry.ordering is None:
            raise self._configuration(
                "relationship_ordering_not_compiled",
                "Relationship does not support writable ordering.",
            )
        current = await self._related_rows(connection, parent_identity, entry)
        target_source = self._target_source(entry)
        current_keys = {
            self._identity_key(target_source.identity_for(row.target)) for row in current
        }
        requested_keys = {self._identity_key(identity) for identity in step.identities}
        if current_keys != requested_keys:
            raise self._conflict("Reorder identities do not match the current relationship state.")
        position_field = str(entry.ordering.position_field)
        resolved = self._resolved(entry)
        for position, identity in enumerate(step.identities):
            if entry.definition.kind is RelationshipKind.ONE_TO_MANY:
                await connection.execute(
                    sa_update(target_source._table)
                    .where(*target_source.identity_conditions(identity))
                    .values({position_field: position})
                )
            elif entry.definition.kind is RelationshipKind.ASSOCIATION_OBJECT:
                association = resolved.target_table
                parent_field = resolved.foreign_key_field
                target_field = resolved.association_target_field
                assert parent_field is not None and target_field is not None
                await connection.execute(
                    sa_update(association)
                    .where(
                        association.c[parent_field]
                        == self._identity_value(self._parent_data_source, parent_identity),
                        association.c[target_field]
                        == self._identity_value(target_source, identity),
                    )
                    .values({position_field: position})
                )
            else:
                raise self._configuration(
                    "relationship_ordering_kind_invalid",
                    "Writable ordering is unsupported for this relationship kind.",
                )

    async def execute_in_uow(
        self,
        uow: SQLAlchemyCoreUnitOfWork,
        *,
        parent_identity: RecordIdentity,
        change: RelationshipChangePlan,
        new_parent: bool = False,
    ) -> RelationshipMutationResult:
        """Apply one neutral graph plan inside an already-owned root UoW."""

        connection = uow.connection
        entry = self._entry(change.relationship_id)
        parent = await self._parent(connection, parent_identity)
        if not new_parent:
            await self._verify_and_claim_parent(connection, parent_identity, parent, entry, change)

        before_rows = await self._related_rows(connection, parent_identity, entry)
        target_source = self._target_source(entry)
        before = tuple(target_source.identity_for(row.target) for row in before_rows)
        added: list[RecordIdentity] = []
        removed: list[RecordIdentity] = []

        for step in change.steps:
            if isinstance(step, SetRelated):
                await self._resolve_targets(connection, entry, (step.identity,))
                await self._set_to_one(connection, parent_identity, entry, step.identity)
            elif isinstance(step, ClearRelated):
                await self._clear_to_one(connection, parent_identity, entry)
            elif isinstance(step, LinkRelated):
                await self._resolve_targets(connection, entry, (step.identity,))
                await self._link_many(connection, parent_identity, entry, step.identity)
            elif isinstance(step, UnlinkRelated):
                await self._unlink_many(connection, parent_identity, entry, step.identity)
            elif isinstance(step, UpdateAssociationRelated):
                await self._resolve_targets(connection, entry, (step.target_identity,))
                await self._update_association(connection, parent_identity, entry, step)
            elif isinstance(step, ReorderRelated):
                await self._reorder(connection, parent_identity, entry, step)
            elif isinstance(step, CreateRelated | UpdateRelated | DeleteRelated):
                raise self._configuration(
                    "relationship_child_mutation_service_required",
                    "Direct child create, update, and delete require an explicit child write service.",
                )
            else:
                raise self._configuration(
                    "relationship_step_unsupported",
                    "SQLAlchemy Core relationship graph step is unsupported.",
                )

        after_rows = await self._related_rows(connection, parent_identity, entry)
        after = tuple(target_source.identity_for(row.target) for row in after_rows)
        before_by_key = {self._identity_key(identity): identity for identity in before}
        after_by_key = {self._identity_key(identity): identity for identity in after}
        for key, identity in after_by_key.items():
            if key not in before_by_key:
                added.append(identity)
        for key, identity in before_by_key.items():
            if key not in after_by_key:
                removed.append(identity)

        return RelationshipMutationResult(
            parent_identity=parent_identity,
            relationship_id=change.relationship_id,
            kind=(
                # Graph plans can contain several concrete edge steps. The
                # neutral receipt uses UPDATE as the aggregate graph intent.
                "update"
            ),
            target_identities=after,
            added_target_identities=tuple(added),
            removed_target_identities=tuple(removed),
        )


__all__ = ["SQLAlchemyCoreRelationshipMutationService"]
