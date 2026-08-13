"""SQLAlchemy-backed scoped relationship resolution and mutation execution."""

import hashlib
import json
import secrets
from collections.abc import Callable, Mapping
from datetime import timedelta
from typing import Any

from rakit_core.concurrency import ConcurrencyTokenService, ConcurrencyVersionProvider
from rakit_core.crypto import TokenService
from rakit_core.errors import ErrorCode, RakitError
from rakit_core.idempotency import (
    IdempotencyReservation,
    IdempotencyStatus,
    IdempotencyStore,
    OperationReceipt,
)
from rakit_core.identity import (
    RecordIdentity,
    canonical_identity_payload,
    identity_from_canonical_payload,
)
from rakit_core.mutations import OperationAuthorization, OperationAuthorizationSet
from rakit_core.operations import OperationContext, current_operation_context
from rakit_core.query import PageResult
from rakit_core.relationship_mutations import (
    AssociationScalarChange,
    ClearRelated,
    CreateRelated,
    DeleteRelated,
    LinkRelated,
    RelationshipCandidate,
    RelationshipChanged,
    RelationshipChangePlan,
    RelationshipEditorRow,
    RelationshipMutationKind,
    RelationshipMutationPlan,
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
from rakit_core.transactions import TransactionPolicy
from sqlalchemy import inspect as sqlalchemy_inspect
from sqlalchemy import update as sqlalchemy_update
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import with_parent

from .datasource import SQLAlchemyDataSource
from .uow import SQLAlchemyUnitOfWork


class SQLAlchemyRelationshipResolver:
    """Resolve relationship parents/targets solely through a resource scope.

    ``resolve`` returns an adapter-private ORM record for the mutation engine;
    public callers use ``candidate`` and receive only identity plus plain text
    label.  Neither path opens or commits a transaction.
    """

    def __init__(self, data_source: SQLAlchemyDataSource) -> None:
        self._data_source = data_source

    async def resolve(self, session: AsyncSession, identity: RecordIdentity) -> object | None:
        return await self._data_source.resolve_scoped(session, identity)

    async def candidate(
        self,
        session: AsyncSession,
        identity: RecordIdentity,
        *,
        label: Callable[[object], str],
    ) -> RelationshipCandidate | None:
        record = await self.resolve(session, identity)
        if record is None:
            return None
        return RelationshipCandidate(
            identity=self._data_source.identity_for(record), label=label(record)
        )


class SQLAlchemyRelationshipMutationService:
    """Execute compiled relationship plans in the existing operation/UoW model.

    The service accepts only canonical identities and an explicit trusted
    capability.  It owns no independent session, authorization policy, event
    queue, or transaction coordinator: every write is performed by
    :class:`SQLAlchemyUnitOfWork` and inherits an active parent UoW when one
    exists.
    """

    def __init__(
        self,
        *,
        session_factory: async_sessionmaker[AsyncSession],
        parent_data_source: SQLAlchemyDataSource,
        relationships: tuple[CompiledRelationship, ...],
        target_data_sources: Mapping[str, SQLAlchemyDataSource],
        token_service: TokenService,
        concurrency_provider: ConcurrencyVersionProvider,
        idempotency_store: IdempotencyStore,
        target_mutation_services: Mapping[str, Any] | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._parent_data_source = parent_data_source
        self._relationships = {entry.definition.relationship_id: entry for entry in relationships}
        self._target_data_sources = dict(target_data_sources)
        self._token_service = token_service
        self._concurrency = ConcurrencyTokenService(token_service)
        self._concurrency_provider = concurrency_provider
        self._idempotency_store = idempotency_store
        self._target_mutation_services = dict(target_mutation_services or {})

        if any(entry.source_resource_id != self._resource_id for entry in relationships):
            raise ValueError("Relationship mutation entries must share the parent resource")
        for entry in relationships:
            target_resource = self._target_resource_id(entry)
            if target_resource not in self._target_data_sources:
                raise ValueError("Every compiled relationship requires a target data source")

    @property
    def _resource_id(self) -> str:
        # Compiled relationships carry the stable resource ID.  A service
        # without relationships has no executable surface and is rejected by
        # the first attempted lookup instead of guessing a table name.
        return (
            next(iter(self._relationships.values())).source_resource_id
            if self._relationships
            else ""
        )

    def _entry(self, relationship_id: str) -> CompiledRelationship:
        entry = self._relationships.get(relationship_id)
        if entry is None:
            raise RakitError(
                code=ErrorCode.CONFIG_INVALID,
                message="Relationship is not compiled for this resource.",
                status_code=500,
            )
        return entry

    @staticmethod
    def _token_resource_id(entry: CompiledRelationship) -> str:
        return f"{entry.source_resource_id}:relationship:{entry.definition.relationship_id}"

    @staticmethod
    def _identity_key(identity: RecordIdentity) -> str:
        return json.dumps(
            canonical_identity_payload(identity), sort_keys=True, separators=(",", ":")
        )

    def _target_resource_id(self, entry: CompiledRelationship) -> str:
        return (
            str(entry.definition.association_target_resource_id)
            if entry.definition.kind is RelationshipKind.ASSOCIATION_OBJECT
            else str(entry.definition.target_resource_id)
        )

    async def issue_concurrency_token(
        self, parent_identity: RecordIdentity, relationship_id: str
    ) -> str:
        """Issue a token binding parent revision and canonical relationship state."""

        entry = self._entry(relationship_id)
        async with self._session_factory() as session:
            parent = await SQLAlchemyRelationshipResolver(self._parent_data_source).resolve(
                session, parent_identity
            )
            if parent is None:
                raise self._not_found()
            digest = await self._state_digest(session, parent, entry)
            return self._concurrency.issue(
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
        """Return scoped, safe editor rows without exposing ORM objects to web.

        The web adapter declares the child fields it is prepared to render from
        the target's authoritative ``FormSchema``.  Relationship/target scope
        is still re-applied here, so a visible parent never becomes an oracle
        for a target hidden by its own resource policy.
        """

        entry = self._entry(relationship_id)
        if not entry.definition.readable:
            return PageResult(
                items=(), page=page, per_page=per_page, has_previous=False, has_next=False
            )
        if page < 1 or per_page < 1 or per_page > 200:
            raise RakitError(
                code=ErrorCode.VALIDATION_FAILED,
                message="Invalid relationship page.",
                status_code=422,
            )
        target_source = self._target_data_sources[self._target_resource_id(entry)]
        async with self._session_factory() as session:
            parent = await SQLAlchemyRelationshipResolver(self._parent_data_source).resolve(
                session, parent_identity
            )
            if parent is None:
                raise self._not_found()
            property_name = str(entry.definition.relationship_id)
            if entry.definition.kind is RelationshipKind.ASSOCIATION_OBJECT:
                target_property = self._association_target_property(entry)
                edge_source = self._target_data_sources[str(entry.definition.target_resource_id)]
                relationship_attribute = getattr(self._parent_data_source._model, property_name)
                edge_target_attribute = getattr(edge_source._model, target_property)
                identity_column = getattr(target_source._model, target_source.identity_fields[0])
                statement = (
                    target_source.scoped_statement()
                    .add_columns(edge_source._model)
                    .join(edge_target_attribute)
                    .where(with_parent(parent, relationship_attribute))
                    .order_by(identity_column.asc())
                    .offset((page - 1) * per_page)
                    .limit(per_page + 1)
                )
                pairs = list((await session.execute(statement)).unique().all())
                has_next = len(pairs) > per_page
                rows = [
                    RelationshipEditorRow(
                        candidate=RelationshipCandidate(
                            identity=target_source.identity_for(target),
                            label=resolve_record_label(entry.definition, target),
                        ),
                        values={
                            field: getattr(edge, field)
                            for field in entry.definition.association_fields
                        },
                        association_identity=edge_source.identity_for(edge),
                    )
                    for target, edge in pairs[:per_page]
                ]
                return PageResult(
                    items=tuple(rows),
                    page=page,
                    per_page=per_page,
                    has_previous=page > 1,
                    has_next=has_next,
                    total_count=None,
                )
            relationship_attribute = getattr(self._parent_data_source._model, property_name)
            identity_column = getattr(target_source._model, target_source.identity_fields[0])
            order_columns = (identity_column.asc(),)
            if entry.ordering is not None:
                position_column = getattr(target_source._model, str(entry.ordering.position_field))
                order_columns = (position_column.asc(), identity_column.asc())
            statement = (
                target_source.scoped_statement()
                .where(with_parent(parent, relationship_attribute))
                .order_by(*order_columns)
                .offset((page - 1) * per_page)
                .limit(per_page + 1)
            )
            records = list((await session.execute(statement)).scalars().unique().all())
            has_next = len(records) > per_page
            records = records[:per_page]
            rows: list[RelationshipEditorRow] = []
            target_mutation_service = self._target_mutation_services.get(
                self._target_resource_id(entry)
            )
            for record in records:
                identity = target_source.identity_for(record)
                token = None
                issue_token = getattr(target_mutation_service, "issue_update_token", None)
                if child_fields and callable(issue_token):
                    token = issue_token(record)
                rows.append(
                    RelationshipEditorRow(
                        candidate=RelationshipCandidate(
                            identity=identity,
                            label=resolve_record_label(entry.definition, record),
                        ),
                        values={field: getattr(record, field) for field in child_fields},
                        concurrency_token=token,
                    )
                )
            return PageResult(
                items=tuple(rows),
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
        """Return a complete, bounded identity-only order for a reorderable editor.

        ``None`` is an intentional fail-closed result: a relationship that is
        too large for the configured UI bound stays editable, but cannot be
        reordered through a partial page.
        """

        entry = self._entry(relationship_id)
        if maximum < 1 or entry.ordering is None:
            return None
        target_source = self._target_data_sources[self._target_resource_id(entry)]
        async with self._session_factory() as session:
            parent = await SQLAlchemyRelationshipResolver(self._parent_data_source).resolve(
                session, parent_identity
            )
            if parent is None:
                raise self._not_found()
            relationship_attribute = getattr(
                self._parent_data_source._model, str(entry.definition.relationship_id)
            )
            identity_field = target_source.identity_fields[0]
            identity_column = getattr(target_source._model, identity_field)
            position_column = getattr(target_source._model, str(entry.ordering.position_field))
            statement = (
                target_source.scoped_statement()
                .with_only_columns(identity_column)
                .where(with_parent(parent, relationship_attribute))
                .order_by(position_column.asc(), identity_column.asc())
                .limit(maximum + 1)
            )
            values = list((await session.execute(statement)).scalars())
            if len(values) > maximum:
                return None
            return tuple(RecordIdentity(values={identity_field: value}) for value in values)

    async def preview_destructive_impact(
        self,
        plan: RelationshipMutationPlan,
        *,
        authorization: OperationAuthorization | None,
    ) -> tuple[RecordIdentity, ...]:
        """Resolve the authoritative delete-orphan impact without writing."""

        entry = self._entry(plan.relationship_id)
        self._validate_plan_owner(plan, entry)
        self._require_authorization(plan, entry, authorization)
        async with self._session_factory() as session:
            parent = await SQLAlchemyRelationshipResolver(self._parent_data_source).resolve(
                session, plan.parent_identity
            )
            if parent is None:
                raise self._not_found()
            await self._verify_concurrency(session, parent, entry, plan)
            before = await self._current_target_identities(session, parent, entry)
            targets = self._destructive_targets(entry, before, plan)
            self._reject_unapproved_destructive_impact(entry, targets)
            return targets

    async def preview_child_delete(
        self,
        parent_identity: RecordIdentity,
        relationship_id: str,
        child_identity: RecordIdentity,
    ) -> object:
        """Prepare a registered child's normal delete preview after membership checks."""

        entry = self._entry(relationship_id)
        if not entry.definition.destructive_policy.allow_child_delete:
            raise RakitError(
                code=ErrorCode.AUTH_FORBIDDEN,
                message="Relationship policy does not allow deleting this child.",
                status_code=403,
            )
        service = self._target_mutation_services.get(self._target_resource_id(entry))
        preview = getattr(service, "preview_delete", None)
        if not callable(preview):
            raise RakitError(
                code=ErrorCode.CONFIG_INVALID,
                message="Relationship target does not support deletion.",
                status_code=500,
            )
        async with self._session_factory() as session:
            parent = await SQLAlchemyRelationshipResolver(self._parent_data_source).resolve(
                session, parent_identity
            )
            if parent is None:
                raise self._not_found()
            members = await self._current_target_identities(session, parent, entry)
            if self._identity_key(child_identity) not in {
                self._identity_key(member) for member in members
            }:
                raise self._not_found()
        return await preview(child_identity)

    async def issue_child_delete_confirmation(
        self,
        parent_identity: RecordIdentity,
        relationship_id: str,
        child_identity: RecordIdentity,
    ) -> str:
        """Issue the target resource's sealed delete confirmation after membership checks."""

        await self.preview_child_delete(parent_identity, relationship_id, child_identity)
        target_resource_id = self._target_resource_id(self._entry(relationship_id))
        service = self._target_mutation_services[target_resource_id]
        issue = getattr(service, "issue_delete_token", None)
        if not callable(issue):
            raise RakitError(
                code=ErrorCode.CONFIG_INVALID,
                message="Relationship target does not support deletion.",
                status_code=500,
            )
        return await issue(child_identity)

    async def validate_parent_proof(
        self,
        change: RelationshipChangePlan,
        parent_identity: RecordIdentity,
        expected_parent_version: object,
    ) -> None:
        """Validate token identity/version before the root parent guard.

        The relationship-state digest is deliberately rechecked only after the
        database-backed guard is claimed by ``execute_in_uow``.
        """

        entry = self._entry(change.relationship_id)
        if not change.concurrency_token:
            raise self._conflict("A relationship concurrency token is required.")
        self._concurrency.verify(
            change.concurrency_token,
            self._token_resource_id(entry),
            parent_identity,
            expected_parent_version,
        )
        base = self._concurrency.base_snapshot(
            change.concurrency_token, self._token_resource_id(entry), parent_identity
        )
        if base.get("relationship_id") != change.relationship_id:
            raise self._conflict("Relationship concurrency proof does not match the relationship.")

    async def execute(
        self,
        plan: RelationshipMutationPlan,
        *,
        authorization: OperationAuthorization | None,
        target_delete_authorizations: tuple[OperationAuthorization, ...] = (),
    ) -> RelationshipMutationResult:
        """Run one non-destructive relationship plan atomically.

        Destructive impact/confirmation is intentionally checked before any
        ORM collection mutation; the initial supported executor handles the
        safe to-one path and grows through the same private apply seam.
        """

        entry = self._entry(plan.relationship_id)
        self._validate_plan_owner(plan, entry)
        context = self._require_authorization(plan, entry, authorization)
        context.checkpoint()
        if plan.concurrency_token is None:
            raise self._conflict("A relationship concurrency token is required.")
        if not plan.idempotency_token:
            raise RakitError(
                code=ErrorCode.VALIDATION_FAILED,
                message="A relationship submission token is required.",
                status_code=400,
            )

        try:
            reservation = await self._idempotency_store.begin(
                hashlib.sha256(plan.idempotency_token.encode("utf-8")).hexdigest(),
                fingerprint=self._idempotency_fingerprint(plan, context),
            )
        except ValueError as exc:
            raise self._conflict(
                "Relationship submission token is bound to another mutation."
            ) from exc
        if reservation.status is IdempotencyStatus.COMPLETED:
            return self._result_from_receipt(reservation.completed_receipt)
        if not reservation.claimed:
            raise self._conflict("Relationship submission is already in progress or final.")

        event_publisher = context.events
        receipt: OperationReceipt | None = None
        callbacks_registered = False
        deleted_targets: tuple[RecordIdentity, ...] = ()
        try:
            async with SQLAlchemyUnitOfWork(
                self._session_factory,
                policy=TransactionPolicy.AUTO,
                event_publisher=event_publisher,
                operation_context=context,
            ) as uow:
                uow.after_commit(lambda: self._complete_reservation(reservation, receipt))
                uow.after_rollback(lambda: self._idempotency_store.release(reservation))
                callbacks_registered = True
                parent = await SQLAlchemyRelationshipResolver(self._parent_data_source).resolve(
                    uow.session, plan.parent_identity
                )
                if parent is None:
                    raise self._not_found()
                expected_version = self._concurrency_provider.version_for(parent)
                await self._claim_parent_concurrency(uow.session, parent, plan.parent_identity)
                await self._verify_concurrency(
                    uow.session, parent, entry, plan, expected_version=expected_version
                )
                targets = await self._resolve_targets(uow.session, entry, plan.target_identities)
                before = await self._current_target_identities(uow.session, parent, entry)
                destructive_targets = self._destructive_targets(entry, before, plan)
                self._reject_unapproved_destructive_impact(entry, destructive_targets)
                if destructive_targets:
                    await self._verify_destructive_execution(
                        uow,
                        plan,
                        entry,
                        context,
                        destructive_targets,
                        target_delete_authorizations,
                        await self._state_digest(uow.session, parent, entry),
                    )
                    deleted_targets = destructive_targets
                after, added, removed = await self._apply(uow.session, parent, entry, plan, targets)
                await uow.session.flush()
                current_token = self._issue_concurrency_token(
                    parent,
                    entry,
                    plan.parent_identity,
                    await self._state_digest(uow.session, parent, entry),
                )
                result = RelationshipMutationResult(
                    parent_identity=plan.parent_identity,
                    relationship_id=plan.relationship_id,
                    kind=plan.kind,
                    target_identities=after,
                    added_target_identities=added,
                    removed_target_identities=removed,
                    deleted_target_identities=deleted_targets,
                    concurrency_token=current_token,
                )
                receipt = self._receipt_for_result(plan.operation_id, result)
                if event_publisher is not None:
                    event_publisher.publish(
                        RelationshipChanged(
                            parent_resource_id=plan.parent_resource_id,
                            parent_identity=plan.parent_identity,
                            relationship_id=plan.relationship_id,
                            kind=plan.kind,
                            added_target_identities=added,
                            removed_target_identities=removed,
                            deleted_target_identities=deleted_targets,
                            operation_id=plan.operation_id,
                        )
                    )
                await uow.mark_success()
        except BaseException:
            if not callbacks_registered:
                await self._idempotency_store.release(reservation)
            raise
        return result

    async def _complete_reservation(
        self, reservation: IdempotencyReservation, receipt: OperationReceipt | None
    ) -> None:
        if receipt is None:
            raise RuntimeError("Relationship mutation did not prepare an idempotency receipt")
        await self._idempotency_store.complete(reservation, receipt)

    async def execute_in_uow(
        self,
        uow: SQLAlchemyUnitOfWork,
        *,
        parent: object,
        parent_identity: RecordIdentity,
        change: RelationshipChangePlan,
        authorizations: OperationAuthorizationSet,
        expected_parent_version: object | None,
        new_parent: bool = False,
    ) -> RelationshipMutationResult:
        """Apply graph-owned relationship work without a nested root lifecycle."""

        entry = self._entry(change.relationship_id)
        context = self._require_composed_relationship_authorization(
            entry, change, parent_identity, authorizations, new_parent=new_parent
        )
        if change.authorization_requirement != entry.mutation_permission:
            raise RakitError(
                code=ErrorCode.AUTH_FORBIDDEN,
                message=(
                    "Relationship mutation requirement does not match the compiled relationship."
                ),
                status_code=403,
            )
        if not new_parent:
            if expected_parent_version is None:
                raise self._configuration_error(
                    "Existing relationship mutation requires a parent concurrency version."
                )
            await self._verify_change_concurrency(
                uow.session, parent, entry, change, parent_identity, expected_parent_version
            )
        before = await self._current_target_identities(uow.session, parent, entry)
        deleted_targets: list[RecordIdentity] = []
        for step in change.steps:
            if isinstance(step, CreateRelated):
                target_service = self._target_mutation_service(entry)
                if entry.target_create_permission is None:
                    raise self._configuration_error(
                        "Child create is not compiled for this relationship."
                    )
                child = await target_service.create_in_uow(
                    uow,
                    step.values,
                    authorizations=authorizations,
                    operation=f"{change.operation_id}:target-create",
                    requirement=entry.target_create_permission,
                    attach_before_flush=(
                        lambda record: self._attach_created_child(parent, entry, record)
                        if self._creates_direct_child(entry)
                        else None
                    ),
                )
                identity = self._target_data_sources[self._target_resource_id(entry)].identity_for(
                    child
                )
                if not self._creates_direct_child(entry):
                    await self._apply(
                        uow.session,
                        parent,
                        entry,
                        self._single_plan(
                            change, parent_identity, RelationshipMutationKind.ADD, identity
                        ),
                        {self._identity_key(identity): child},
                    )
            elif isinstance(step, LinkRelated):
                targets = await self._resolve_targets(uow.session, entry, (step.identity,))
                await self._apply(
                    uow.session,
                    parent,
                    entry,
                    self._single_plan(
                        change, parent_identity, RelationshipMutationKind.ADD, step.identity
                    ),
                    targets,
                )
            elif isinstance(step, SetRelated):
                targets = await self._resolve_targets(uow.session, entry, (step.identity,))
                plan = self._single_plan(
                    change, parent_identity, RelationshipMutationKind.SET, step.identity
                )
                current = await self._current_target_identities(uow.session, parent, entry)
                destructive = self._destructive_targets(entry, current, plan)
                self._reject_unapproved_destructive_impact(entry, destructive)
                if destructive:
                    await self._verify_destructive_execution(
                        uow,
                        plan,
                        entry,
                        context,
                        destructive,
                        (authorizations.root, *authorizations.capabilities),
                        await self._state_digest(uow.session, parent, entry),
                    )
                    deleted_targets.extend(destructive)
                await self._apply(
                    uow.session,
                    parent,
                    entry,
                    plan,
                    targets,
                )
            elif isinstance(step, ClearRelated):
                plan = self._single_plan(change, parent_identity, RelationshipMutationKind.CLEAR)
                current = await self._current_target_identities(uow.session, parent, entry)
                destructive = self._destructive_targets(entry, current, plan)
                self._reject_unapproved_destructive_impact(entry, destructive)
                if destructive:
                    await self._verify_destructive_execution(
                        uow,
                        plan,
                        entry,
                        context,
                        destructive,
                        (authorizations.root, *authorizations.capabilities),
                        await self._state_digest(uow.session, parent, entry),
                    )
                    deleted_targets.extend(destructive)
                await self._apply(uow.session, parent, entry, plan, {})
            elif isinstance(step, UnlinkRelated):
                plan = self._single_plan(
                    change, parent_identity, RelationshipMutationKind.REMOVE, step.identity
                )
                current = await self._current_target_identities(uow.session, parent, entry)
                destructive = self._destructive_targets(entry, current, plan)
                self._reject_unapproved_destructive_impact(entry, destructive)
                if destructive:
                    await self._verify_destructive_execution(
                        uow,
                        plan,
                        entry,
                        context,
                        destructive,
                        (authorizations.root, *authorizations.capabilities),
                        await self._state_digest(uow.session, parent, entry),
                    )
                    deleted_targets.extend(destructive)
                targets = await self._resolve_targets(uow.session, entry, (step.identity,))
                await self._apply(uow.session, parent, entry, plan, targets)
            elif isinstance(step, UpdateRelated):
                await self._require_related_member(uow.session, parent, entry, step.identity)
                target_service = self._target_mutation_service(entry)
                if entry.target_update_permission is None:
                    raise self._configuration_error(
                        "Child update is not compiled for this relationship."
                    )
                await target_service.update_in_uow(
                    uow,
                    step.identity,
                    step.values,
                    concurrency_token=step.concurrency_token,
                    authorizations=authorizations,
                    operation=f"{change.operation_id}:target-update",
                    requirement=entry.target_update_permission,
                )
            elif isinstance(step, DeleteRelated):
                await self._require_related_member(uow.session, parent, entry, step.identity)
                if not entry.definition.destructive_policy.allow_child_delete:
                    raise RakitError(
                        code=ErrorCode.VALIDATION_FAILED,
                        message="Relationship policy does not permit child deletion.",
                        status_code=422,
                    )
                if entry.target_delete_permission is None or not step.confirmation_token:
                    raise RakitError(
                        code=ErrorCode.AUTH_FORBIDDEN,
                        message="Child deletion requires exact authorization and confirmation.",
                        status_code=403,
                    )
                target_service = self._target_mutation_service(entry)
                await target_service.delete_in_uow(
                    uow,
                    step.confirmation_token,
                    identity=step.identity,
                    authorizations=authorizations,
                    operation=f"{change.operation_id}:target-delete",
                    requirement=entry.target_delete_permission,
                )
                deleted_targets.append(step.identity)
            elif isinstance(step, UpdateAssociationRelated):
                targets = await self._resolve_targets(uow.session, entry, (step.target_identity,))
                await self._apply(
                    uow.session,
                    parent,
                    entry,
                    self._association_plan(change, parent_identity, step),
                    targets,
                )
            elif isinstance(step, ReorderRelated):
                await self._apply_reorder(uow.session, parent, entry, step)
            else:  # pragma: no cover - discriminated core plan guards this branch.
                raise self._configuration_error("Unsupported relationship graph step.")
        await uow.session.flush()
        after = await self._current_target_identities(uow.session, parent, entry)
        before_keys = {self._identity_key(identity): identity for identity in before}
        after_keys = {self._identity_key(identity): identity for identity in after}
        added = tuple(identity for key, identity in after_keys.items() if key not in before_keys)
        removed = tuple(identity for key, identity in before_keys.items() if key not in after_keys)
        token = self._issue_concurrency_token(
            parent, entry, parent_identity, await self._state_digest(uow.session, parent, entry)
        )
        result = RelationshipMutationResult(
            parent_identity=parent_identity,
            relationship_id=change.relationship_id,
            kind=RelationshipMutationKind.UPDATE,
            target_identities=after,
            added_target_identities=added,
            removed_target_identities=removed,
            deleted_target_identities=tuple(deleted_targets),
            concurrency_token=token,
        )
        if uow.event_publisher is not None:
            uow.event_publisher.publish(
                RelationshipChanged(
                    parent_resource_id=entry.source_resource_id,
                    parent_identity=parent_identity,
                    relationship_id=change.relationship_id,
                    kind=RelationshipMutationKind.UPDATE,
                    added_target_identities=added,
                    removed_target_identities=removed,
                    deleted_target_identities=tuple(deleted_targets),
                    operation_id=change.operation_id,
                )
            )
        return result

    def _require_composed_relationship_authorization(
        self,
        entry: CompiledRelationship,
        change: RelationshipChangePlan,
        parent_identity: RecordIdentity,
        authorizations: OperationAuthorizationSet,
        *,
        new_parent: bool = False,
    ) -> OperationContext:
        context = current_operation_context()
        root = authorizations.root
        if (
            context is None
            or context.principal is None
            or context.admin_id != root.admin_id
            or context.principal.subject_id != root.principal_id
            or context.resource_id != root.resource_id
            or context.operation != root.operation
            or context.permission_requirement != root.requirement
        ):
            raise RakitError(
                code=ErrorCode.AUTH_FORBIDDEN,
                message="Graph authorization does not match the active operation.",
                status_code=403,
            )
        try:
            authorizations.require(
                resource_id=entry.source_resource_id,
                operation=change.operation_id,
                requirement=entry.mutation_permission,
                # A create graph cannot bind a capability to a database
                # identity that does not exist until after flush.  Its route
                # boundary therefore authorizes the relationship operation
                # against the new-parent sentinel; existing-parent graph work
                # remains identity-bound exactly as before.
                target_identity=None if new_parent else parent_identity,
            )
        except ValueError as exc:
            raise RakitError(
                code=ErrorCode.AUTH_FORBIDDEN,
                message="Relationship mutation requires an exact authorization capability.",
                status_code=403,
            ) from exc
        return context

    async def _verify_change_concurrency(
        self,
        session: AsyncSession,
        parent: object,
        entry: CompiledRelationship,
        change: RelationshipChangePlan,
        parent_identity: RecordIdentity,
        expected_parent_version: object,
    ) -> None:
        if not change.concurrency_token:
            raise self._conflict("A relationship concurrency token is required.")
        self._concurrency.verify(
            change.concurrency_token,
            self._token_resource_id(entry),
            parent_identity,
            expected_parent_version,
        )
        base = self._concurrency.base_snapshot(
            change.concurrency_token, self._token_resource_id(entry), parent_identity
        )
        if base.get("relationship_id") != change.relationship_id or base.get(
            "relationship_state_digest"
        ) != await self._state_digest(session, parent, entry):
            raise self._conflict("The relationship changed since this mutation was prepared.")

    def _single_plan(
        self,
        change: RelationshipChangePlan,
        parent_identity: RecordIdentity,
        kind: RelationshipMutationKind,
        identity: RecordIdentity | None = None,
    ) -> RelationshipMutationPlan:
        return RelationshipMutationPlan(
            operation_id=change.operation_id,
            parent_resource_id=self._resource_id,
            parent_identity=parent_identity,
            relationship_id=change.relationship_id,
            kind=kind,
            target_identities=(identity,) if identity is not None else (),
            authorization_requirement=change.authorization_requirement,
            concurrency_token=change.concurrency_token,
            destructive_confirmation=change.destructive_confirmation,
        )

    def _association_plan(
        self,
        change: RelationshipChangePlan,
        parent_identity: RecordIdentity,
        step: UpdateAssociationRelated,
    ) -> RelationshipMutationPlan:
        """Translate the typed graph edge update into the approved Phase-2 plan."""

        return RelationshipMutationPlan(
            operation_id=change.operation_id,
            parent_resource_id=self._resource_id,
            parent_identity=parent_identity,
            relationship_id=change.relationship_id,
            kind=RelationshipMutationKind.UPDATE,
            target_identities=(step.target_identity,),
            association_changes=(
                AssociationScalarChange(
                    target_identity=step.target_identity,
                    association_identity=step.association_identity,
                    values=step.values,
                ),
            ),
            authorization_requirement=change.authorization_requirement,
            concurrency_token=change.concurrency_token,
            destructive_confirmation=change.destructive_confirmation,
        )

    def _target_mutation_service(self, entry: CompiledRelationship) -> Any:
        service = self._target_mutation_services.get(self._target_resource_id(entry))
        if service is None:
            raise self._configuration_error(
                "Inline relationship mutation requires the target resource write service."
            )
        return service

    @staticmethod
    def _creates_direct_child(entry: CompiledRelationship) -> bool:
        return (
            entry.definition.kind is RelationshipKind.ONE_TO_MANY
            and entry.definition.cardinality is RelationshipCardinality.TO_MANY
        )

    @staticmethod
    def _attach_created_child(parent: object, entry: CompiledRelationship, child: object) -> None:
        """Link a new direct child before its first flush establishes a required FK."""

        collection = getattr(parent, str(entry.definition.relationship_id))
        collection.append(child)

    async def _require_related_member(
        self,
        session: AsyncSession,
        parent: object,
        entry: CompiledRelationship,
        identity: RecordIdentity,
    ) -> None:
        if self._identity_key(identity) not in {
            self._identity_key(value)
            for value in await self._current_target_identities(session, parent, entry)
        }:
            raise RakitError(
                code=ErrorCode.RESOURCE_NOT_FOUND,
                message="Resource was not found.",
                status_code=404,
            )

    async def _apply_reorder(
        self,
        session: AsyncSession,
        parent: object,
        entry: CompiledRelationship,
        step: ReorderRelated,
    ) -> None:
        ordering = entry.ordering
        if ordering is None:
            raise RakitError(
                code=ErrorCode.VALIDATION_FAILED,
                message="Relationship is ordered but not safely reorderable.",
                status_code=422,
            )
        if entry.definition.kind is not RelationshipKind.ONE_TO_MANY:
            raise self._configuration_error(
                "Only direct one-to-many relationships support reorder."
            )
        relationship_id = str(entry.definition.relationship_id)
        await session.refresh(parent, attribute_names=[relationship_id])
        current = getattr(parent, relationship_id)
        target_source = self._target_data_sources[self._target_resource_id(entry)]
        members = {
            self._identity_key(target_source.identity_for(record)): record for record in current
        }
        desired = tuple(step.identities)
        desired_keys = tuple(self._identity_key(identity) for identity in desired)
        if len(desired_keys) != len(members) or set(desired_keys) != set(members):
            raise RakitError(
                code=ErrorCode.VALIDATION_FAILED,
                message="Reorder must contain every current relationship member exactly once.",
                status_code=422,
            )
        offset = (
            len(members)
            + max((int(getattr(record, ordering.position_field)) for record in current), default=0)
            + 1
        )
        for index, key in enumerate(desired_keys):
            setattr(members[key], ordering.position_field, offset + index)
        await session.flush()
        for index, key in enumerate(desired_keys):
            setattr(members[key], ordering.position_field, index)
        await session.flush()

    @staticmethod
    def _configuration_error(message: str) -> RakitError:
        return RakitError(code=ErrorCode.CONFIG_INVALID, message=message, status_code=500)

    @staticmethod
    def _receipt_for_result(
        operation_id: str, result: RelationshipMutationResult
    ) -> OperationReceipt:
        def identity_list(
            values: tuple[RecordIdentity, ...],
        ) -> list[dict[str, dict[str, int | str]]]:
            return [canonical_identity_payload(value) for value in values]

        return OperationReceipt(
            operation_id=operation_id,
            status="succeeded",
            result_kind="relationship_mutation",
            payload={
                "parent_identity": canonical_identity_payload(result.parent_identity),
                "relationship_id": result.relationship_id,
                "kind": result.kind.value,
                "target_identities": identity_list(result.target_identities),
                "added_target_identities": identity_list(result.added_target_identities),
                "removed_target_identities": identity_list(result.removed_target_identities),
                "deleted_target_identities": identity_list(result.deleted_target_identities),
                "concurrency_token": result.concurrency_token,
            },
        )

    @staticmethod
    def _result_from_receipt(receipt: OperationReceipt | None) -> RelationshipMutationResult:
        if (
            receipt is None
            or receipt.result_kind != "relationship_mutation"
            or receipt.payload is None
        ):
            raise RakitError(
                code=ErrorCode.RESOURCE_CONFLICT,
                message="Completed relationship submission has no valid receipt.",
                status_code=409,
            )
        payload = receipt.payload
        try:
            kind = RelationshipMutationKind(str(payload["kind"]))

            def identities(field: str) -> tuple[RecordIdentity, ...]:
                values = payload.get(field, [])
                if not isinstance(values, list):
                    raise ValueError
                if not all(isinstance(value, Mapping) for value in values):
                    raise ValueError
                return tuple(identity_from_canonical_payload(value) for value in values)

            parent = payload.get("parent_identity")
            relationship_id = payload.get("relationship_id")
            if not isinstance(parent, Mapping) or not isinstance(relationship_id, str):
                raise ValueError
            token = payload.get("concurrency_token")
            return RelationshipMutationResult(
                parent_identity=identity_from_canonical_payload(parent),
                relationship_id=relationship_id,
                kind=kind,
                target_identities=identities("target_identities"),
                added_target_identities=identities("added_target_identities"),
                removed_target_identities=identities("removed_target_identities"),
                deleted_target_identities=identities("deleted_target_identities"),
                concurrency_token=token if isinstance(token, str) else None,
                replayed=True,
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise RakitError(
                code=ErrorCode.RESOURCE_CONFLICT,
                message="Completed relationship submission has no valid receipt.",
                status_code=409,
            ) from exc

    def _validate_plan_owner(
        self, plan: RelationshipMutationPlan, entry: CompiledRelationship
    ) -> None:
        if (
            plan.parent_resource_id != entry.source_resource_id
            or plan.authorization_requirement != entry.mutation_permission
            or not entry.definition.effective_writable
        ):
            raise RakitError(
                code=ErrorCode.AUTH_FORBIDDEN,
                message="Relationship mutation does not match the compiled relationship policy.",
                status_code=403,
            )

    @staticmethod
    def _idempotency_fingerprint(plan: RelationshipMutationPlan, context: OperationContext) -> str:
        """Bind durable submission ownership to the server-derived operation context."""

        payload = {
            "plan": plan.fingerprint,
            "admin_id": context.admin_id,
            "principal_id": context.principal_id,
            "session_id": context.session_id,
        }
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(encoded.encode("utf-8")).hexdigest()

    def _require_authorization(
        self,
        plan: RelationshipMutationPlan,
        entry: CompiledRelationship,
        authorization: OperationAuthorization | None,
    ):
        context = current_operation_context()
        if (
            context is None
            or authorization is None
            or context.principal is None
            or context.admin_id != authorization.admin_id
            or context.principal.subject_id != authorization.principal_id
            or context.resource_id != entry.source_resource_id
            or context.operation != plan.operation_id
            or context.permission_requirement != entry.mutation_permission
            or authorization.resource_id != entry.source_resource_id
            or authorization.operation != plan.operation_id
            or authorization.target_identity != plan.parent_identity
            or authorization.requirement != entry.mutation_permission
        ):
            raise RakitError(
                code=ErrorCode.AUTH_FORBIDDEN,
                message="Relationship mutation requires an exact authorization capability.",
                status_code=403,
            )
        return context

    async def _resolve_targets(
        self,
        session: AsyncSession,
        entry: CompiledRelationship,
        identities: tuple[RecordIdentity, ...],
    ) -> dict[str, object]:
        resolver = SQLAlchemyRelationshipResolver(
            self._target_data_sources[self._target_resource_id(entry)]
        )
        records: dict[str, object] = {}
        for identity in identities:
            record = await resolver.resolve(session, identity)
            if record is None:
                raise self._not_found()
            records[self._identity_key(identity)] = record
        return records

    async def _current_target_identities(
        self, session: AsyncSession, parent: object, entry: CompiledRelationship
    ) -> tuple[RecordIdentity, ...]:
        await session.refresh(parent, attribute_names=[str(entry.definition.relationship_id)])
        value = getattr(parent, entry.definition.relationship_id)
        target_source = self._target_data_sources[self._target_resource_id(entry)]
        if entry.definition.kind is RelationshipKind.ASSOCIATION_OBJECT:
            target_property = self._association_target_property(entry)
            for edge in value:
                await session.refresh(edge, attribute_names=[target_property])
            return tuple(
                sorted(
                    (target_source.identity_for(getattr(edge, target_property)) for edge in value),
                    key=self._identity_key,
                )
            )
        if entry.definition.cardinality is RelationshipCardinality.TO_ONE:
            return () if value is None else (target_source.identity_for(value),)
        return tuple(
            sorted((target_source.identity_for(record) for record in value), key=self._identity_key)
        )

    async def _state_digest(
        self, session: AsyncSession, parent: object, entry: CompiledRelationship
    ) -> str:
        identities = await self._current_target_identities(session, parent, entry)
        payload = {
            "relationship_id": entry.definition.relationship_id,
            "target_identities": [canonical_identity_payload(identity) for identity in identities],
        }
        if entry.definition.kind is RelationshipKind.ASSOCIATION_OBJECT:
            relationship_id = str(entry.definition.relationship_id)
            edge_source = self._target_data_sources[str(entry.definition.target_resource_id)]
            target_property = self._association_target_property(entry)
            edges = getattr(parent, relationship_id)
            for edge in edges:
                await session.refresh(edge, attribute_names=[target_property])
            payload["association_entries"] = sorted(
                (
                    {
                        "association_identity": canonical_identity_payload(
                            edge_source.identity_for(edge)
                        ),
                        "target_identity": canonical_identity_payload(
                            self._target_data_sources[self._target_resource_id(entry)].identity_for(
                                getattr(edge, target_property)
                            )
                        ),
                        "values": ConcurrencyTokenService.canonical_snapshot(
                            {
                                field: getattr(edge, field)
                                for field in entry.definition.association_fields
                            }
                        ),
                    }
                    for edge in edges
                ),
                key=lambda value: self._identity_key(
                    identity_from_canonical_payload(value["target_identity"])
                ),
            )
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(encoded.encode("utf-8")).hexdigest()

    async def _verify_concurrency(
        self,
        session: AsyncSession,
        parent: object,
        entry: CompiledRelationship,
        plan: RelationshipMutationPlan,
        *,
        expected_version: object | None = None,
    ) -> None:
        assert plan.concurrency_token is not None
        self._concurrency.verify(
            plan.concurrency_token,
            self._token_resource_id(entry),
            plan.parent_identity,
            expected_version
            if expected_version is not None
            else self._concurrency_provider.version_for(parent),
        )
        base = self._concurrency.base_snapshot(
            plan.concurrency_token, self._token_resource_id(entry), plan.parent_identity
        )
        if base.get("relationship_id") != plan.relationship_id or base.get(
            "relationship_state_digest"
        ) != await self._state_digest(session, parent, entry):
            raise self._conflict("The relationship changed since this mutation was prepared.")

    async def _claim_parent_concurrency(
        self, session: AsyncSession, parent: object, identity: RecordIdentity
    ) -> None:
        """Advance the mapped version with an atomic scoped predicate.

        This is the relationship write's database concurrency boundary.  The
        subsequent digest verification occurs only after the guarded row has
        been advanced and reloaded, so two transactions from the same base
        state cannot both proceed to mutate relationship rows.
        """

        current = self._concurrency_provider.predicate_values_for(parent)
        next_values = self._concurrency_provider.next_values_for(parent)
        if not current or not next_values:
            raise RakitError(
                code=ErrorCode.CONFIG_INVALID,
                message=(
                    "Relationship mutation requires an atomically advanceable concurrency version."
                ),
                status_code=500,
            )
        model = self._parent_data_source._model
        identity_fields = self._parent_data_source.identity_fields
        scoped_identity = (
            self._parent_data_source.scoped_statement()
            .where(*self._parent_data_source.identity_conditions(identity))
            .with_only_columns(getattr(model, identity_fields[0]))
        )
        result = await session.execute(
            sqlalchemy_update(model)
            .where(
                getattr(model, identity_fields[0]).in_(scoped_identity.scalar_subquery()),
                *(getattr(model, field) == value for field, value in current.items()),
            )
            .values(**dict(next_values))
        )
        if not isinstance(result, CursorResult) or result.rowcount != 1:
            raise self._conflict("The relationship changed since this mutation was prepared.")
        await session.refresh(parent)

    def _issue_concurrency_token(
        self,
        parent: object,
        entry: CompiledRelationship,
        parent_identity: RecordIdentity,
        relationship_state_digest: str,
    ) -> str:
        return self._concurrency.issue(
            self._token_resource_id(entry),
            parent_identity,
            self._concurrency_provider.version_for(parent),
            base_snapshot={
                "relationship_id": entry.definition.relationship_id,
                "relationship_state_digest": relationship_state_digest,
            },
        )

    async def _apply(
        self,
        session: AsyncSession,
        parent: object,
        entry: CompiledRelationship,
        plan: RelationshipMutationPlan,
        targets: Mapping[str, object],
    ) -> tuple[tuple[RecordIdentity, ...], tuple[RecordIdentity, ...], tuple[RecordIdentity, ...]]:
        if entry.definition.kind is RelationshipKind.ASSOCIATION_OBJECT:
            return await self._apply_association_object(session, parent, entry, plan, targets)
        relationship_id = str(entry.definition.relationship_id)
        before = await self._current_target_identities(session, parent, entry)
        before_keys = {self._identity_key(identity): identity for identity in before}
        requested = tuple(plan.target_identities)
        requested_keys = {self._identity_key(identity): identity for identity in requested}
        value = getattr(parent, relationship_id)

        if entry.definition.cardinality is RelationshipCardinality.TO_ONE:
            if plan.kind is RelationshipMutationKind.SET:
                setattr(parent, relationship_id, targets[self._identity_key(requested[0])])
                after = requested
            elif plan.kind is RelationshipMutationKind.CLEAR:
                if not entry.definition.nullable:
                    raise RakitError(
                        code=ErrorCode.VALIDATION_FAILED,
                        message="A required relationship cannot be cleared.",
                        status_code=422,
                    )
                setattr(parent, relationship_id, None)
                after = ()
            else:
                raise RakitError(
                    code=ErrorCode.VALIDATION_FAILED,
                    message="This operation is not valid for a to-one relationship.",
                    status_code=422,
                )
        else:
            if plan.kind is RelationshipMutationKind.ADD:
                for identity in requested:
                    if self._identity_key(identity) not in before_keys:
                        value.append(targets[self._identity_key(identity)])
                after = tuple(
                    sorted(
                        (
                            *before,
                            *(
                                identity
                                for identity in requested
                                if self._identity_key(identity) not in before_keys
                            ),
                        ),
                        key=self._identity_key,
                    )
                )
            elif plan.kind is RelationshipMutationKind.REMOVE:
                for record in tuple(value):
                    if (
                        self._identity_key(
                            self._target_data_sources[self._target_resource_id(entry)].identity_for(
                                record
                            )
                        )
                        in requested_keys
                    ):
                        value.remove(record)
                after = tuple(
                    identity
                    for identity in before
                    if self._identity_key(identity) not in requested_keys
                )
            elif plan.kind is RelationshipMutationKind.REPLACE:
                value[:] = [targets[self._identity_key(identity)] for identity in requested]
                after = requested
            else:
                raise RakitError(
                    code=ErrorCode.VALIDATION_FAILED,
                    message="This operation is not valid for a to-many relationship.",
                    status_code=422,
                )

        after_keys = {self._identity_key(identity): identity for identity in after}
        added = tuple(identity for key, identity in after_keys.items() if key not in before_keys)
        removed = tuple(identity for key, identity in before_keys.items() if key not in after_keys)
        return after, added, removed

    def _removed_target_identities(
        self,
        before: tuple[RecordIdentity, ...],
        plan: RelationshipMutationPlan,
    ) -> tuple[RecordIdentity, ...]:
        before_keys = {self._identity_key(identity): identity for identity in before}
        requested_keys = {self._identity_key(identity) for identity in plan.target_identities}
        if plan.kind is RelationshipMutationKind.CLEAR:
            return before
        if plan.kind is RelationshipMutationKind.SET:
            return tuple(
                identity for key, identity in before_keys.items() if key not in requested_keys
            )
        if plan.kind is RelationshipMutationKind.REMOVE:
            return tuple(identity for key, identity in before_keys.items() if key in requested_keys)
        if plan.kind is RelationshipMutationKind.REPLACE:
            return tuple(
                identity for key, identity in before_keys.items() if key not in requested_keys
            )
        return ()

    def _destructive_targets(
        self,
        entry: CompiledRelationship,
        before: tuple[RecordIdentity, ...],
        plan: RelationshipMutationPlan,
    ) -> tuple[RecordIdentity, ...]:
        removed = self._removed_target_identities(before, plan)
        if not removed:
            return ()
        metadata = self._parent_data_source.relationship_metadata.get(
            entry.definition.relationship_id
        )
        if metadata is None:
            raise RakitError(
                code=ErrorCode.CONFIG_INVALID,
                message="Relationship mapper metadata is unavailable.",
                status_code=500,
            )
        if entry.definition.kind is RelationshipKind.ASSOCIATION_OBJECT and plan.kind in {
            RelationshipMutationKind.REMOVE,
            RelationshipMutationKind.REPLACE,
        }:
            # Phase 2 association-object REMOVE/REPLACE operations delete the
            # edge object, not the semantic end target.  Parent-side
            # delete-orphan therefore cleans up the association row only;
            # target deletion would require a distinct semantic operation.
            return ()
        # ``delete`` cascade applies when the parent itself is deleted.  This
        # operation only de-associates children, so only delete-orphan can
        # make the related target disappear here.
        if not metadata.delete_orphan:
            return ()
        return removed

    def _reject_unapproved_destructive_impact(
        self, entry: CompiledRelationship, destructive_targets: tuple[RecordIdentity, ...]
    ) -> None:
        if not destructive_targets:
            return
        metadata = self._parent_data_source.relationship_metadata[entry.definition.relationship_id]
        policy = entry.definition.destructive_policy
        if metadata.delete_orphan and not policy.allow_delete_orphan:
            raise RakitError(
                code=ErrorCode.VALIDATION_FAILED,
                message=(
                    "Relationship change could delete an orphaned record without policy approval."
                ),
                status_code=422,
            )

    async def issue_destructive_confirmation(
        self,
        plan: RelationshipMutationPlan,
        *,
        authorization: OperationAuthorization | None,
    ) -> str:
        """Issue a purpose-separated confirmation bound to current destructive impact."""

        entry = self._entry(plan.relationship_id)
        self._validate_plan_owner(plan, entry)
        context = self._require_authorization(plan, entry, authorization)
        async with self._session_factory() as session:
            parent = await SQLAlchemyRelationshipResolver(self._parent_data_source).resolve(
                session, plan.parent_identity
            )
            if parent is None:
                raise self._not_found()
            await self._verify_concurrency(session, parent, entry, plan)
            before = await self._current_target_identities(session, parent, entry)
            destructive_targets = self._destructive_targets(entry, before, plan)
            self._reject_unapproved_destructive_impact(entry, destructive_targets)
            if not destructive_targets:
                raise RakitError(
                    code=ErrorCode.VALIDATION_FAILED,
                    message="Relationship change has no persistent destructive impact to confirm.",
                    status_code=422,
                )
            digest = await self._state_digest(session, parent, entry)
        targets = [canonical_identity_payload(identity) for identity in destructive_targets]
        impact = hashlib.sha256(
            json.dumps(targets, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        return self._token_service.issue_in(
            "relationship_destructive_confirmation",
            {
                "admin_id": context.admin_id,
                "principal_id": context.principal_id,
                "session_id": context.session_id,
                "parent_resource_id": plan.parent_resource_id,
                "parent_identity": canonical_identity_payload(plan.parent_identity),
                "relationship_id": plan.relationship_id,
                "kind": plan.kind.value,
                "targets": targets,
                "relationship_state_digest": digest,
                "impact_digest": impact,
                "nonce": secrets.token_urlsafe(32),
            },
            timedelta(minutes=15),
        )

    async def _verify_destructive_execution(
        self,
        uow: SQLAlchemyUnitOfWork,
        plan: RelationshipMutationPlan,
        entry: CompiledRelationship,
        context: OperationContext,
        destructive_targets: tuple[RecordIdentity, ...],
        target_delete_authorizations: tuple[OperationAuthorization, ...],
        current_digest: str,
    ) -> None:
        if entry.target_delete_permission is None:
            raise RakitError(
                code=ErrorCode.CONFIG_INVALID,
                message=(
                    "Destructive relationship mutation has no compiled target delete permission."
                ),
                status_code=500,
            )
        # Scope remains an independent boundary even for targets currently
        # attached to a visible parent.
        await self._resolve_targets(uow.session, entry, destructive_targets)
        by_target = {
            self._identity_key(authorization.target_identity): authorization
            for authorization in target_delete_authorizations
            if authorization.target_identity is not None
        }
        for identity in destructive_targets:
            capability = by_target.get(self._identity_key(identity))
            if (
                capability is None
                or capability.admin_id != context.admin_id
                or capability.principal_id != context.principal_id
                or capability.resource_id != self._target_resource_id(entry)
                or capability.operation != f"{plan.operation_id}:target-delete"
                or capability.requirement != entry.target_delete_permission
            ):
                raise RakitError(
                    code=ErrorCode.AUTH_FORBIDDEN,
                    message=(
                        "Destructive relationship mutation requires exact target "
                        "delete authorization."
                    ),
                    status_code=403,
                )
        if not plan.destructive_confirmation:
            raise RakitError(
                code=ErrorCode.AUTH_FORBIDDEN,
                message="Destructive relationship mutation requires confirmation.",
                status_code=403,
            )
        try:
            claims = self._token_service.verify(
                plan.destructive_confirmation,
                expected_purpose="relationship_destructive_confirmation",
            )
        except ValueError as exc:
            raise RakitError(
                code=ErrorCode.AUTH_FORBIDDEN,
                message="Invalid destructive relationship confirmation.",
                status_code=403,
            ) from exc
        targets = [canonical_identity_payload(identity) for identity in destructive_targets]
        impact = hashlib.sha256(
            json.dumps(targets, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        if (
            claims.get("admin_id") != context.admin_id
            or claims.get("principal_id") != context.principal_id
            or claims.get("session_id") != context.session_id
            or claims.get("parent_resource_id") != plan.parent_resource_id
            or claims.get("parent_identity") != canonical_identity_payload(plan.parent_identity)
            or claims.get("relationship_id") != plan.relationship_id
            or claims.get("kind") != plan.kind.value
            or claims.get("targets") != targets
            or claims.get("relationship_state_digest") != current_digest
            or claims.get("impact_digest") != impact
        ):
            raise RakitError(
                code=ErrorCode.AUTH_FORBIDDEN,
                message="Destructive relationship confirmation does not match this mutation.",
                status_code=403,
            )
        reservation = await self._idempotency_store.begin(
            hashlib.sha256(plan.destructive_confirmation.encode("utf-8")).hexdigest(),
            fingerprint=f"destructive:{plan.fingerprint}:{impact}",
        )
        if not reservation.claimed:
            raise self._conflict("Destructive relationship confirmation has already been used.")
        receipt = OperationReceipt(
            operation_id=plan.operation_id,
            status="succeeded",
            result_kind="relationship_destructive_confirmation",
        )
        uow.after_commit(lambda: self._idempotency_store.complete(reservation, receipt))
        uow.after_rollback(lambda: self._idempotency_store.release(reservation))

    def _association_target_property(self, entry: CompiledRelationship) -> str:
        metadata = self._parent_data_source.relationship_metadata.get(
            entry.definition.relationship_id
        )
        target_property = getattr(metadata, "association_target_relationship_id", None)
        if not isinstance(target_property, str) or not target_property:
            raise RakitError(
                code=ErrorCode.CONFIG_INVALID,
                message="Association-object relationship metadata is incomplete.",
                status_code=500,
            )
        return target_property

    async def _apply_association_object(
        self,
        session: AsyncSession,
        parent: object,
        entry: CompiledRelationship,
        plan: RelationshipMutationPlan,
        targets: Mapping[str, object],
    ) -> tuple[tuple[RecordIdentity, ...], tuple[RecordIdentity, ...], tuple[RecordIdentity, ...]]:
        """Apply the intentionally small association-object boundary.

        Edge primary keys and parent/target FKs are established solely by ORM
        relationship assignment.  The only mass-assignment surface is the
        explicit, Phase-1 validated scalar allow-list.
        """

        relationship_id = str(entry.definition.relationship_id)
        await session.refresh(parent, attribute_names=[relationship_id])
        edges = getattr(parent, relationship_id)
        edge_source = self._target_data_sources[str(entry.definition.target_resource_id)]
        target_source = self._target_data_sources[self._target_resource_id(entry)]
        target_property = self._association_target_property(entry)
        existing: dict[str, object] = {}
        for edge in edges:
            await session.refresh(edge, attribute_names=[target_property])
            key = self._identity_key(target_source.identity_for(getattr(edge, target_property)))
            if key in existing:
                raise RakitError(
                    code=ErrorCode.CONFIG_INVALID,
                    message="Association-object mapping has ambiguous duplicate target edges.",
                    status_code=500,
                )
            existing[key] = edge

        allowed_fields = set(entry.definition.association_fields)
        changes = {
            self._identity_key(change.target_identity): change
            for change in plan.association_changes
        }
        for key, change in changes.items():
            if not set(change.values) <= allowed_fields:
                raise RakitError(
                    code=ErrorCode.VALIDATION_FAILED,
                    message="Association scalar field is not editable.",
                    status_code=422,
                )
            edge = existing.get(key)
            if change.association_identity is not None and (
                edge is None or edge_source.identity_for(edge) != change.association_identity
            ):
                raise RakitError(
                    code=ErrorCode.VALIDATION_FAILED,
                    message="Association identity does not match the current relationship edge.",
                    status_code=422,
                )

        before = tuple(
            sorted(
                (target_source.identity_for(getattr(edge, target_property)) for edge in edges),
                key=self._identity_key,
            )
        )
        before_keys = {self._identity_key(identity): identity for identity in before}
        requested = tuple(plan.target_identities)
        requested_keys = {self._identity_key(identity): identity for identity in requested}
        if plan.kind is RelationshipMutationKind.CLEAR or plan.kind is RelationshipMutationKind.SET:
            raise RakitError(
                code=ErrorCode.VALIDATION_FAILED,
                message="This operation is not valid for an association-object relationship.",
                status_code=422,
            )

        if plan.kind in {RelationshipMutationKind.REMOVE, RelationshipMutationKind.REPLACE}:
            for key, edge in tuple(existing.items()):
                if plan.kind is RelationshipMutationKind.REMOVE:
                    should_remove = key in requested_keys
                else:
                    should_remove = key not in requested_keys
                if should_remove:
                    # An association object is the persistence representation
                    # of the relationship edge.  Removing it is deliberately
                    # not target deletion, even when its foreign keys are
                    # non-nullable and the parent relationship lacks
                    # delete-orphan cascade.
                    await session.delete(edge)
                    edges.remove(edge)
                    existing.pop(key)

        if plan.kind in {
            RelationshipMutationKind.ADD,
            RelationshipMutationKind.UPDATE,
            RelationshipMutationKind.REPLACE,
        }:
            mapper = sqlalchemy_inspect(type(parent))
            assert mapper is not None
            edge_model = mapper.relationships[relationship_id].mapper.class_
            for identity in requested:
                key = self._identity_key(identity)
                edge = existing.get(key)
                if edge is None:
                    if plan.kind is RelationshipMutationKind.UPDATE:
                        raise RakitError(
                            code=ErrorCode.VALIDATION_FAILED,
                            message="Association edge does not exist for update.",
                            status_code=422,
                        )
                    edge = edge_model()
                    setattr(edge, target_property, targets[key])
                    edges.append(edge)
                    existing[key] = edge
                change = changes.get(key)
                if change is not None:
                    for field, value in change.values.items():
                        setattr(edge, field, value)

        after = tuple(
            sorted(
                (target_source.identity_for(getattr(edge, target_property)) for edge in edges),
                key=self._identity_key,
            )
        )
        after_keys = {self._identity_key(identity): identity for identity in after}
        added = tuple(identity for key, identity in after_keys.items() if key not in before_keys)
        removed = tuple(identity for key, identity in before_keys.items() if key not in after_keys)
        return after, added, removed

    async def _replayed_result(
        self, plan: RelationshipMutationPlan, entry: CompiledRelationship
    ) -> RelationshipMutationResult:
        async with self._session_factory() as session:
            parent = await SQLAlchemyRelationshipResolver(self._parent_data_source).resolve(
                session, plan.parent_identity
            )
            if parent is None:
                raise self._not_found()
            targets = await self._current_target_identities(session, parent, entry)
        return RelationshipMutationResult(
            parent_identity=plan.parent_identity,
            relationship_id=plan.relationship_id,
            kind=plan.kind,
            target_identities=targets,
            concurrency_token=await self.issue_concurrency_token(
                plan.parent_identity, plan.relationship_id
            ),
            replayed=True,
        )

    @staticmethod
    def _not_found() -> RakitError:
        return RakitError(
            code=ErrorCode.RESOURCE_NOT_FOUND,
            message="Resource was not found.",
            status_code=404,
        )

    @staticmethod
    def _conflict(message: str) -> RakitError:
        return RakitError(code=ErrorCode.RESOURCE_CONFLICT, message=message, status_code=409)


__all__ = ["SQLAlchemyRelationshipMutationService", "SQLAlchemyRelationshipResolver"]
