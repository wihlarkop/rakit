"""SQLAlchemy-backed scoped relationship resolution and mutation execution."""

import hashlib
import json
from collections.abc import Callable, Mapping

from rakit_core.concurrency import ConcurrencyTokenService, ConcurrencyVersionProvider
from rakit_core.crypto import TokenService
from rakit_core.errors import ErrorCode, RakitError
from rakit_core.idempotency import IdempotencyStatus, IdempotencyStore, OperationReceipt
from rakit_core.identity import RecordIdentity
from rakit_core.mutations import OperationAuthorization
from rakit_core.operations import current_operation_context
from rakit_core.relationship_mutations import (
    RelationshipCandidate,
    RelationshipChanged,
    RelationshipMutationKind,
    RelationshipMutationPlan,
    RelationshipMutationResult,
)
from rakit_core.relationships import CompiledRelationship, RelationshipCardinality, RelationshipKind
from rakit_core.transactions import TransactionPolicy
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

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
    ) -> None:
        self._session_factory = session_factory
        self._parent_data_source = parent_data_source
        self._relationships = {entry.definition.relationship_id: entry for entry in relationships}
        self._target_data_sources = dict(target_data_sources)
        self._concurrency = ConcurrencyTokenService(token_service)
        self._concurrency_provider = concurrency_provider
        self._idempotency_store = idempotency_store

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
        return json.dumps(dict(identity.values), sort_keys=True, separators=(",", ":"))

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

    async def execute(
        self,
        plan: RelationshipMutationPlan,
        *,
        authorization: OperationAuthorization | None,
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

        reservation = await self._idempotency_store.begin(
            hashlib.sha256(plan.idempotency_token.encode("utf-8")).hexdigest(),
            fingerprint=plan.fingerprint,
        )
        if reservation.status is IdempotencyStatus.COMPLETED:
            return await self._replayed_result(plan, entry)
        if not reservation.claimed:
            raise self._conflict("Relationship submission is already in progress or final.")

        event_publisher = context.events
        try:
            async with SQLAlchemyUnitOfWork(
                self._session_factory,
                policy=TransactionPolicy.AUTO,
                event_publisher=event_publisher,
                operation_context=context,
            ) as uow:
                parent = await SQLAlchemyRelationshipResolver(self._parent_data_source).resolve(
                    uow.session, plan.parent_identity
                )
                if parent is None:
                    raise self._not_found()
                await self._verify_concurrency(uow.session, parent, entry, plan)
                targets = await self._resolve_targets(uow.session, entry, plan.target_identities)
                after, added, removed = await self._apply(uow.session, parent, entry, plan, targets)
                await uow.session.flush()
                if event_publisher is not None:
                    event_publisher.publish(
                        RelationshipChanged(
                            parent_resource_id=plan.parent_resource_id,
                            parent_identity=plan.parent_identity,
                            relationship_id=plan.relationship_id,
                            kind=plan.kind,
                            added_target_identities=added,
                            removed_target_identities=removed,
                            operation_id=plan.operation_id,
                        )
                    )
                await uow.mark_success()
            current_token = await self.issue_concurrency_token(
                plan.parent_identity, plan.relationship_id
            )
            result = RelationshipMutationResult(
                parent_identity=plan.parent_identity,
                relationship_id=plan.relationship_id,
                kind=plan.kind,
                target_identities=after,
                added_target_identities=added,
                removed_target_identities=removed,
                concurrency_token=current_token,
            )
        except BaseException:
            await self._idempotency_store.release(reservation)
            raise
        await self._idempotency_store.complete(
            reservation,
            OperationReceipt(
                operation_id=plan.operation_id,
                status="succeeded",
                result_kind="relationship_mutation",
            ),
        )
        return result

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
            "target_identities": [dict(identity.values) for identity in identities],
        }
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(encoded.encode("utf-8")).hexdigest()

    async def _verify_concurrency(
        self,
        session: AsyncSession,
        parent: object,
        entry: CompiledRelationship,
        plan: RelationshipMutationPlan,
    ) -> None:
        assert plan.concurrency_token is not None
        self._concurrency.verify(
            plan.concurrency_token,
            self._token_resource_id(entry),
            plan.parent_identity,
            self._concurrency_provider.version_for(parent),
        )
        base = self._concurrency.base_snapshot(
            plan.concurrency_token, self._token_resource_id(entry), plan.parent_identity
        )
        if base.get("relationship_id") != plan.relationship_id or base.get(
            "relationship_state_digest"
        ) != await self._state_digest(session, parent, entry):
            raise self._conflict("The relationship changed since this mutation was prepared.")

    async def _apply(
        self,
        session: AsyncSession,
        parent: object,
        entry: CompiledRelationship,
        plan: RelationshipMutationPlan,
        targets: Mapping[str, object],
    ) -> tuple[tuple[RecordIdentity, ...], tuple[RecordIdentity, ...], tuple[RecordIdentity, ...]]:
        if entry.definition.kind is RelationshipKind.ASSOCIATION_OBJECT:
            raise RakitError(
                code=ErrorCode.CONFIG_INVALID,
                message="Association-object mutation is not yet configured for this relationship.",
                status_code=500,
            )
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
