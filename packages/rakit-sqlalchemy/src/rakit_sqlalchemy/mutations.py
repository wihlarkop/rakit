"""SQLAlchemy execution for the framework-neutral write pipeline."""

import hashlib
from collections.abc import Callable, Mapping
from datetime import datetime, timedelta
from typing import Any, cast

from rakit_core.concurrency import (
    AttributeVersionProvider,
    ConcurrencyConflict,
    ConcurrencyMode,
    ConcurrencyTokenService,
    ConcurrencyVersionProvider,
    SnapshotVersionProvider,
)
from rakit_core.crypto import TokenService
from rakit_core.deletion import DeletionPlan
from rakit_core.errors import ErrorCode, RakitError
from rakit_core.events import EventBus, EventPublisher
from rakit_core.forms import FormSchema, FormValidationError
from rakit_core.idempotency import IdempotencyStore, OperationReceipt
from rakit_core.identity import RecordIdentity
from rakit_core.mutations import (
    MutationAuthorization,
    MutationHooks,
    MutationResult,
    ResourceCreated,
    ResourceDeleted,
    ResourceForceOverwritten,
    ResourceMutationPlan,
    ResourceUpdated,
    UpdateMutationPlan,
    run_after_commit_hooks,
    run_mutation_hooks,
)
from rakit_core.operations import current_operation_context
from rakit_core.transactions import TransactionPolicy
from sqlalchemy import Select, inspect, select
from sqlalchemy import delete as sqlalchemy_delete
from sqlalchemy import update as sqlalchemy_update
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import Mapper
from sqlalchemy.sql.elements import ColumnElement

from .uow import SQLAlchemyUnitOfWork


def _validation_error(exc: ValueError) -> RakitError:
    return RakitError(
        code=ErrorCode.VALIDATION_FAILED,
        message="Invalid form submission",
        status_code=422,
        cause=exc,
    )


class SQLAlchemyMutationService:
    """Apply a compiled form schema to explicitly writable ORM attributes.

    This service is intentionally not a generic ``setattr`` escape hatch:
    the form schema rejects unknown keys and this executor independently
    checks the compiled writable allowlist before touching a mapped record.
    """

    def __init__(
        self,
        *,
        model: type[object],
        session_factory: async_sessionmaker[AsyncSession],
        form_schema: FormSchema,
        writable_fields: tuple[str, ...],
        identity_fields: tuple[str, ...],
        event_publisher: EventPublisher | None = None,
        token_service: TokenService | None = None,
        version_field: str | None = None,
        concurrency_mode: ConcurrencyMode | None = None,
        concurrency_provider: ConcurrencyVersionProvider | None = None,
        resource_id: str | None = None,
        delete_nonce_store: IdempotencyStore | None = None,
        delete_permission: str | None = None,
        force_overwrite_permission: str | None = None,
        delete_relationship_impact: tuple[str, ...] = (),
        hooks: MutationHooks | None = None,
        scoped_statement: Callable[[], Select] | None = None,
    ) -> None:
        if not writable_fields or not identity_fields:
            raise ValueError("Writable and identity fields must be explicitly declared")
        if len(set(writable_fields)) != len(writable_fields):
            raise ValueError("Writable fields must be unique")
        self._model = model
        self._session_factory = session_factory
        self._form_schema = form_schema
        self._writable_fields = frozenset(writable_fields)
        self._identity_fields = identity_fields
        # A publisher owns deferred transaction state and cannot be shared by
        # this long-lived service.  Keep only its application-scoped bus as a
        # compatibility source for direct host calls without an operation
        # context; each such call receives a fresh publisher below.
        self._event_bus = event_publisher.bus if event_publisher is not None else None
        mode = concurrency_mode or (
            ConcurrencyMode.AUTO if token_service is not None else ConcurrencyMode.DISABLED
        )
        if mode is not ConcurrencyMode.DISABLED and token_service is None:
            raise ValueError("Configured concurrency requires a token service")
        self._version_field = version_field
        self._token_service = token_service
        self._resource_id = resource_id or str(getattr(model, "__tablename__", model.__name__))
        self._delete_nonce_store = delete_nonce_store
        self._delete_permission = delete_permission or f"resources.{self._resource_id}.delete"
        self._force_overwrite_permission = force_overwrite_permission or (
            f"resources.{self._resource_id}.force_overwrite"
        )
        # Relationship/cascade impact is derived from mapped metadata, not
        # caller-supplied presentation text.  Keep the legacy argument only
        # as a declaration guard while Plan 04 callers migrate: it may not
        # claim impact which the mapper does not actually expose.
        mapper_impact = self._relationship_impact()
        if delete_relationship_impact and delete_relationship_impact != mapper_impact:
            raise ValueError("Delete relationship impact must match mapped relationships")
        self._delete_relationship_impact = mapper_impact
        self._hooks = hooks or MutationHooks()
        self._scoped_statement = scoped_statement or (lambda: select(self._model))
        self._concurrency_mode = mode
        self._concurrency_provider = self._resolve_concurrency_provider(concurrency_provider)
        if mode is ConcurrencyMode.REQUIRED and self._concurrency_provider is None:
            raise ValueError("Required concurrency has no safe provider")
        self._concurrency = (
            ConcurrencyTokenService(token_service)
            if token_service is not None and self._concurrency_provider is not None
            else None
        )

    def bind_delete_nonce_store(self, store: IdempotencyStore) -> None:
        """Attach Admin's validated durable receipt store to delete confirmations."""
        self._delete_nonce_store = store

    @property
    def event_bus(self) -> EventBus | None:
        """Optional direct-host bus declaration, never deferred event state."""
        return self._event_bus

    def _operation_event_publisher(self) -> EventPublisher | None:
        context = current_operation_context()
        if context is not None and context.events is not None:
            return context.events
        if self._event_bus is not None:
            return EventPublisher(self._event_bus)
        return None

    def bind_scoped_statement(self, statement: Callable[[], Select]) -> None:
        """Bind the owning resource's canonical visibility selectable."""
        self._scoped_statement = statement

    def _require_authorization(
        self,
        authorization: MutationAuthorization | None,
        operation: str,
    ) -> MutationAuthorization:
        if (
            authorization is None
            or authorization.resource_id != self._resource_id
            or authorization.operation != operation
            or not authorization.admin_id
            or not authorization.principal_id
            or not authorization.permissions
        ):
            raise RakitError(
                code=ErrorCode.AUTH_FORBIDDEN,
                message="Mutation is not authorized.",
                status_code=403,
            )
        context = current_operation_context()
        if (
            context is None
            or context.principal is None
            or any(
                (
                    context.admin_id != authorization.admin_id,
                    context.resource_id != authorization.resource_id,
                    context.operation != authorization.operation,
                    context.principal.subject_id != authorization.principal_id,
                    context.permissions != authorization.permissions,
                )
            )
        ):
            raise RakitError(
                code=ErrorCode.AUTH_FORBIDDEN,
                message="Mutation authorization does not match this operation.",
                status_code=403,
            )
        return authorization

    def prepare_create(self, submitted: Mapping[str, Any]) -> ResourceMutationPlan:
        try:
            state = self._form_schema.parse(submitted)
        except (FormValidationError, ValueError) as exc:
            raise _validation_error(exc) from exc
        values = dict(state.normalized)
        # parse is FormSchema.parse; the remaining pre-persistence phases
        # receive the immutable plan in create/update below.
        if not set(values).issubset(self._writable_fields):
            raise _validation_error(ValueError("Field is not writable"))
        return ResourceMutationPlan(operation="create", values=values)

    def prepare_update(
        self,
        identity: RecordIdentity,
        current_record: object,
        submitted: Mapping[str, Any],
        *,
        concurrency_token: str | None,
    ) -> UpdateMutationPlan:
        create_plan = self.prepare_create(submitted)
        metadata: dict[str, Any] = {}
        if self._concurrency_provider is not None:
            metadata["version"] = self._concurrency_provider.version_for(current_record)
        return UpdateMutationPlan(
            identity=identity,
            current_record=current_record,
            scalar_changes=create_plan.values,
            relationship_changes={},
            concurrency_token=concurrency_token,
            concurrency_metadata=metadata,
        )

    async def create(
        self,
        submitted: Mapping[str, Any],
        *,
        authorization: MutationAuthorization | None = None,
    ) -> MutationResult:
        plan = self.prepare_create(submitted)
        event_publisher = self._operation_event_publisher()
        try:
            await run_mutation_hooks(self._hooks.normalize, plan)
            await run_mutation_hooks(self._hooks.business_validate, plan)
            await run_mutation_hooks(self._hooks.prepare, plan)
            authorized = self._require_authorization(authorization, "create")
            await run_mutation_hooks(self._hooks.authorize, authorized)
            await run_mutation_hooks(self._hooks.pre_event, plan)
            await run_mutation_hooks(self._hooks.before_execute, plan)
            async with SQLAlchemyUnitOfWork(
                self._session_factory,
                policy=TransactionPolicy.AUTO,
                event_publisher=event_publisher,
                operation_context=current_operation_context(),
            ) as uow:
                record = self._model(**dict(plan.values))
                uow.session.add(record)
                await run_mutation_hooks(self._hooks.after_execute, plan)
                await uow.session.flush()
                await run_mutation_hooks(self._hooks.after_flush, plan)
                identity = self._identity_for(record)
                if event_publisher is not None:
                    event_publisher.publish(ResourceCreated(identity=identity))
                await run_mutation_hooks(self._hooks.before_commit, plan)
                await uow.mark_success()
        except BaseException as exc:
            await run_mutation_hooks(self._hooks.after_rollback, exc)
            raise
        result = MutationResult(identity=identity, record=record)
        await run_after_commit_hooks(self._hooks.after_commit, result)
        return result

    def issue_update_token(self, record: object) -> str:
        if self._concurrency is None or self._concurrency_provider is None:
            raise RuntimeError("This resource has no configured concurrency provider")
        return self._concurrency.issue(
            self._resource_id,
            self._identity_for(record),
            self._concurrency_provider.version_for(record),
            base_snapshot=self._safe_snapshot(record),
        )

    async def get(self, identity: RecordIdentity) -> object | None:
        """Load one record for a write form without exposing ORM query internals."""
        if set(identity.values) != set(self._identity_fields):
            raise RakitError(
                code=ErrorCode.VALIDATION_FAILED,
                message="Invalid resource identity",
                status_code=400,
            )
        async with self._session_factory() as session:
            return await self._load(session, identity)

    async def update(
        self,
        identity: RecordIdentity,
        submitted: Mapping[str, Any],
        *,
        concurrency_token: str | None = None,
        authorization: MutationAuthorization | None = None,
        force_overwrite: bool = False,
        force_overwrite_confirmation: str | None = None,
    ) -> MutationResult:
        if set(identity.values) != set(self._identity_fields):
            raise RakitError(
                code=ErrorCode.VALIDATION_FAILED,
                message="Invalid resource identity",
                status_code=400,
            )
        event_publisher = self._operation_event_publisher()
        try:
            async with SQLAlchemyUnitOfWork(
                self._session_factory,
                policy=TransactionPolicy.AUTO,
                event_publisher=event_publisher,
                operation_context=current_operation_context(),
            ) as uow:
                record = await self._load(uow.session, identity)
                if record is None:
                    raise RakitError(
                        code=ErrorCode.RESOURCE_NOT_FOUND,
                        message="Resource was not found",
                        status_code=404,
                    )
                plan = self.prepare_update(
                    identity, record, submitted, concurrency_token=concurrency_token
                )
                await run_mutation_hooks(self._hooks.normalize_update, plan)
                await run_mutation_hooks(self._hooks.business_validate_update, plan)
                await run_mutation_hooks(self._hooks.prepare_update, plan)
                authorized = self._require_authorization(authorization, "update")
                if force_overwrite:
                    self._verify_force_overwrite(force_overwrite_confirmation, identity, authorized)
                await run_mutation_hooks(self._hooks.authorize, authorized)
                await run_mutation_hooks(self._hooks.pre_event, plan)
                await run_mutation_hooks(self._hooks.execute_update, plan)
                await run_mutation_hooks(self._hooks.before_execute, plan)
                if (
                    not force_overwrite
                    and self._concurrency is not None
                    and self._concurrency_provider is not None
                ):
                    if not concurrency_token:
                        raise RakitError(
                            code=ErrorCode.RESOURCE_CONFLICT,
                            message="A concurrency token is required.",
                            status_code=409,
                        )
                    base_snapshot = self._concurrency.base_snapshot(
                        concurrency_token, self._resource_id, identity
                    )
                    try:
                        self._concurrency.verify(
                            concurrency_token,
                            self._resource_id,
                            identity,
                            self._concurrency_provider.version_for(record),
                        )
                    except RakitError as exc:
                        if exc.code == ErrorCode.RESOURCE_CONFLICT:
                            raise self._conflict(record, plan, base_snapshot) from exc
                        raise
                    # The in-memory token check above makes stale forms pleasant
                    # to reject, but it cannot protect two independent database
                    # transactions that both read the same revision.  Put the
                    # expected revision in the UPDATE predicate as well: exactly
                    # one of concurrent writers can affect a row.
                    scoped_identity = (
                        self._scoped_statement()
                        .where(*self._identity_conditions(identity))
                        .with_only_columns(getattr(self._model, self._identity_fields[0]))
                    )
                    result = cast(
                        CursorResult[Any],
                        await uow.session.execute(
                            sqlalchemy_update(self._model)
                            .where(
                                getattr(self._model, self._identity_fields[0]).in_(
                                    scoped_identity.scalar_subquery()
                                ),
                                *self._concurrency_conditions(record),
                            )
                            .values(
                                **dict(plan.scalar_changes),
                                **self._next_concurrency_values(record),
                            )
                        ),
                    )
                    await run_mutation_hooks(self._hooks.after_execute, plan)
                    if result.rowcount != 1:
                        await uow.session.refresh(record)
                        raise self._conflict(record, plan, base_snapshot)
                    await uow.session.refresh(record)
                    await uow.session.flush()
                else:
                    # A force overwrite intentionally omits the stale-version
                    # predicate, but it must never omit the resource scope at
                    # the actual write boundary.
                    base_snapshot = self._safe_snapshot(record)
                    scoped_identity = (
                        self._scoped_statement()
                        .where(*self._identity_conditions(identity))
                        .with_only_columns(getattr(self._model, self._identity_fields[0]))
                    )
                    result = cast(
                        CursorResult[Any],
                        await uow.session.execute(
                            sqlalchemy_update(self._model)
                            .where(
                                getattr(self._model, self._identity_fields[0]).in_(
                                    scoped_identity.scalar_subquery()
                                )
                            )
                            .values(**dict(plan.scalar_changes))
                        ),
                    )
                    if result.rowcount != 1:
                        await uow.session.refresh(record)
                        raise self._conflict(record, plan, base_snapshot)
                    await uow.session.refresh(record)
                    await run_mutation_hooks(self._hooks.after_execute, plan)
                    await uow.session.flush()
                await run_mutation_hooks(self._hooks.after_flush, plan)
                if event_publisher is not None:
                    event = (
                        ResourceForceOverwritten(
                            identity=identity, changed_fields=tuple(plan.scalar_changes)
                        )
                        if force_overwrite
                        else ResourceUpdated(
                            identity=identity, changed_fields=tuple(plan.scalar_changes)
                        )
                    )
                    event_publisher.publish(event)
                await run_mutation_hooks(self._hooks.before_commit, plan)
                await uow.mark_success()
        except BaseException as exc:
            await run_mutation_hooks(self._hooks.after_rollback, exc)
            raise
        mutation_result = MutationResult(identity=identity, record=record)
        await run_after_commit_hooks(self._hooks.after_commit, mutation_result)
        return mutation_result

    async def preview_delete(self, identity: RecordIdentity) -> DeletionPlan:
        if self._token_service is None or self._concurrency_provider is None:
            raise RuntimeError("Delete requires a configured token and version provider")
        async with self._session_factory() as session:
            record = await self._load(session, identity)
            if record is None:
                raise RakitError(
                    code=ErrorCode.RESOURCE_NOT_FOUND,
                    message="Resource was not found",
                    status_code=404,
                )
            return DeletionPlan(
                identity=identity,
                expected_version=self._concurrency_provider.version_for(record),
                relationship_impact=self._delete_relationship_impact,
                required_permission=self._delete_permission,
            )

    def issue_force_overwrite_confirmation(self, identity: RecordIdentity) -> str:
        if self._token_service is None:
            raise RuntimeError("Force overwrite requires a configured token service")
        return self._token_service.issue_in(
            "force_overwrite",
            {"resource_id": self._resource_id, "identity": dict(identity.values)},
            timedelta(minutes=5),
        )

    async def issue_delete_token(self, identity: RecordIdentity) -> str:
        if self._token_service is None:
            raise RuntimeError("Delete requires a configured token service")
        plan = await self.preview_delete(identity)
        return self._token_service.issue_in(
            "delete_confirmation",
            {
                "resource_id": self._resource_id,
                "identity": dict(plan.identity.values),
                "expected_version": plan.expected_version,
                "relationship_impact": plan.relationship_impact,
                "required_permission": plan.required_permission,
                "nonce": plan.nonce,
            },
            timedelta(minutes=15),
        )

    async def delete(
        self,
        confirmation_token: str,
        *,
        identity: RecordIdentity | None = None,
        authorization: MutationAuthorization | None = None,
    ) -> None:
        if self._token_service is None or self._concurrency_provider is None:
            raise RuntimeError("Delete requires a configured token and version provider")
        if self._delete_nonce_store is None:
            raise RakitError(
                code=ErrorCode.CONFIG_INVALID,
                message="Delete requires a durable confirmation store.",
                status_code=500,
            )
        authorized = self._require_authorization(authorization, "delete")
        event_publisher = self._operation_event_publisher()
        target_identity = identity
        reservation = None
        try:
            claims = self._token_service.verify(
                confirmation_token, expected_purpose="delete_confirmation"
            )
            confirmed_identity = RecordIdentity(values=claims["identity"])
            expected_version = claims["expected_version"]
            relationship_impact = tuple(claims["relationship_impact"])
            required_permission = claims["required_permission"]
            if (
                claims.get("resource_id") != self._resource_id
                or set(confirmed_identity.values) != set(self._identity_fields)
                or (
                    relationship_impact != self._delete_relationship_impact
                    or required_permission != self._delete_permission
                )
            ):
                raise ValueError
        except (KeyError, TypeError, ValueError) as exc:
            raise RakitError(
                code=ErrorCode.VALIDATION_FAILED,
                message="Invalid delete confirmation.",
                status_code=400,
                cause=exc,
            ) from exc
        if target_identity is not None and target_identity != confirmed_identity:
            raise RakitError(
                code=ErrorCode.VALIDATION_FAILED,
                message="Invalid delete confirmation.",
                status_code=400,
            )
        await run_mutation_hooks(self._hooks.normalize, confirmed_identity)
        await run_mutation_hooks(self._hooks.business_validate, confirmed_identity)
        await run_mutation_hooks(self._hooks.prepare, confirmed_identity)
        reservation = await self._delete_nonce_store.begin(
            hashlib.sha256(confirmation_token.encode()).hexdigest(),
            fingerprint=f"{self._resource_id}:{dict(confirmed_identity.values)}",
        )
        if not reservation.claimed:
            raise RakitError(
                code=ErrorCode.RESOURCE_CONFLICT,
                message="Delete confirmation has already been used.",
                status_code=409,
            )
        try:
            await run_mutation_hooks(self._hooks.authorize, authorized)
            await run_mutation_hooks(self._hooks.pre_event, confirmed_identity)
            await run_mutation_hooks(self._hooks.before_execute, confirmed_identity)
            async with SQLAlchemyUnitOfWork(
                self._session_factory,
                policy=TransactionPolicy.AUTO,
                event_publisher=event_publisher,
                operation_context=current_operation_context(),
            ) as uow:
                record = await self._load(uow.session, confirmed_identity)
                if record is None:
                    raise RakitError(
                        code=ErrorCode.RESOURCE_NOT_FOUND,
                        message="Resource was not found",
                        status_code=404,
                    )
                if self._concurrency_provider.version_for(record) != expected_version:
                    raise RakitError(
                        code=ErrorCode.RESOURCE_CONFLICT,
                        message="The resource has changed since deletion was confirmed.",
                        status_code=409,
                    )
                scoped_identity = (
                    self._scoped_statement()
                    .where(*self._identity_conditions(confirmed_identity))
                    .with_only_columns(getattr(self._model, self._identity_fields[0]))
                )
                result = cast(
                    CursorResult[Any],
                    await uow.session.execute(
                        sqlalchemy_delete(self._model).where(
                            getattr(self._model, self._identity_fields[0]).in_(
                                scoped_identity.scalar_subquery()
                            ),
                            *self._concurrency_conditions(record),
                        )
                    ),
                )
                if result.rowcount != 1:
                    raise RakitError(
                        code=ErrorCode.RESOURCE_CONFLICT,
                        message="The resource was changed by another request.",
                        status_code=409,
                    )
                await uow.session.flush()
                if event_publisher is not None:
                    event_publisher.publish(ResourceDeleted(identity=confirmed_identity))
                await run_mutation_hooks(self._hooks.before_commit, confirmed_identity)
                await uow.mark_success()
        except BaseException as exc:
            await self._delete_nonce_store.release(reservation)
            await run_mutation_hooks(self._hooks.after_rollback, exc)
            raise
        await self._delete_nonce_store.complete(
            reservation,
            OperationReceipt(
                operation_id=reservation.reservation_id.__str__(),
                status="succeeded",
                result_kind="delete",
            ),
        )
        await run_after_commit_hooks(self._hooks.after_commit, confirmed_identity)

    async def _load(self, session: AsyncSession, identity: RecordIdentity) -> object | None:
        return (
            await session.scalars(
                self._scoped_statement().where(*self._identity_conditions(identity))
            )
        ).one_or_none()

    def _identity_conditions(self, identity: RecordIdentity) -> list[ColumnElement[bool]]:
        return [
            cast(ColumnElement[bool], getattr(self._model, name) == value)
            for name, value in identity.values.items()
        ]

    def _identity_for(self, record: object) -> RecordIdentity:
        return RecordIdentity(
            values={name: getattr(record, name) for name in self._identity_fields}
        )

    def _relationship_impact(self) -> tuple[str, ...]:
        """Return a stable, signed summary of ORM-owned delete impact."""
        mapper = cast(Mapper[Any], inspect(self._model))
        return tuple(
            f"{relationship.key}:{','.join(sorted(relationship.cascade))}"
            for relationship in sorted(mapper.relationships, key=lambda item: item.key)
        )

    def _resolve_concurrency_provider(
        self, explicit: ConcurrencyVersionProvider | None
    ) -> ConcurrencyVersionProvider | None:
        if self._concurrency_mode is ConcurrencyMode.DISABLED:
            return None
        if explicit is not None:
            return explicit
        mapper = cast(Mapper[Any], inspect(self._model))
        if mapper.version_id_col is not None:
            key = mapper.version_id_col.key
            if isinstance(key, str):
                return AttributeVersionProvider(key)
        if self._version_field is not None and self._attribute_version_is_safe(self._version_field):
            return AttributeVersionProvider(self._version_field)
        for field in ("revision", "updated_at"):
            if hasattr(self._model, field) and self._attribute_version_is_safe(field):
                return AttributeVersionProvider(field)
        safe_fields = tuple(
            field.field_id
            for field in self._form_schema.fields
            if field.readable and not field.sensitive and hasattr(self._model, field.field_id)
        )
        return SnapshotVersionProvider(safe_fields) if safe_fields else None

    def _attribute_version_is_safe(self, field: str) -> bool:
        """Only auto-select scalar versions the provider can advance atomically."""
        mapper = cast(Mapper[Any], inspect(self._model))
        attribute = mapper.attrs.get(field)
        columns = getattr(attribute, "columns", ())
        if not columns:
            return False
        try:
            python_type = columns[0].type.python_type
        except (AttributeError, NotImplementedError):
            return False
        return python_type in (int, datetime)

    def _concurrency_conditions(self, record: object) -> tuple[ColumnElement[bool], ...]:
        provider = self._concurrency_provider
        if provider is None:
            return ()
        return tuple(
            cast(ColumnElement[bool], getattr(self._model, field) == value)
            for field, value in provider.predicate_values_for(record).items()
        )

    def _next_concurrency_values(self, record: object) -> Mapping[str, Any]:
        provider = self._concurrency_provider
        return {} if provider is None else provider.next_values_for(record)

    def _safe_snapshot(self, record: object) -> dict[str, Any]:
        values = {
            field.field_id: getattr(record, field.field_id)
            for field in self._form_schema.fields
            if field.readable and not field.sensitive and hasattr(record, field.field_id)
        }
        return ConcurrencyTokenService.canonical_snapshot(values)

    def _conflict(
        self, record: object, plan: UpdateMutationPlan, base: Mapping[str, Any]
    ) -> RakitError:
        current = self._safe_snapshot(record)
        proposed = {
            **base,
            **ConcurrencyTokenService.canonical_snapshot(dict(plan.scalar_changes)),
        }
        conflict = ConcurrencyConflict(
            base=dict(base),
            current=current,
            proposed=proposed,
            field_conflicts=tuple(
                name
                for name, value in plan.scalar_changes.items()
                if base.get(name) != current.get(name) and current.get(name) != value
            ),
        )
        return RakitError(
            code=ErrorCode.RESOURCE_CONFLICT,
            message="The resource was changed by another request.",
            status_code=409,
            details={"conflict": conflict.to_public_dict()},
        )

    def _verify_force_overwrite(
        self,
        confirmation: str | None,
        identity: RecordIdentity,
        authorization: MutationAuthorization,
    ) -> None:
        if self._token_service is None or confirmation is None:
            raise RakitError(
                code=ErrorCode.AUTH_FORBIDDEN,
                message="Force overwrite requires confirmed authorization.",
                status_code=403,
            )
        try:
            claims = self._token_service.verify(confirmation, expected_purpose="force_overwrite")
        except ValueError as exc:
            raise RakitError(
                code=ErrorCode.AUTH_FORBIDDEN,
                message="Force overwrite requires confirmed authorization.",
                status_code=403,
            ) from exc
        if (
            self._force_overwrite_permission not in authorization.permissions
            or claims.get("resource_id") != self._resource_id
            or claims.get("identity") != dict(identity.values)
        ):
            raise RakitError(
                code=ErrorCode.AUTH_FORBIDDEN,
                message="Force overwrite requires confirmed authorization.",
                status_code=403,
            )


__all__ = [
    "ResourceCreated",
    "ResourceDeleted",
    "ResourceForceOverwritten",
    "ResourceUpdated",
    "SQLAlchemyMutationService",
]
