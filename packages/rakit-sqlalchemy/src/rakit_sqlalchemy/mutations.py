"""SQLAlchemy execution for the framework-neutral write pipeline."""

import hashlib
from collections.abc import Mapping
from datetime import timedelta
from typing import Any, cast

from rakit_core.concurrency import ConcurrencyTokenService
from rakit_core.crypto import TokenService
from rakit_core.deletion import DeletionPlan
from rakit_core.errors import ErrorCode, RakitError
from rakit_core.events import EventPublisher
from rakit_core.forms import FormSchema, FormValidationError
from rakit_core.idempotency import IdempotencyStore, OperationReceipt
from rakit_core.identity import RecordIdentity
from rakit_core.mutations import (
    MutationHooks,
    MutationResult,
    ResourceCreated,
    ResourceDeleted,
    ResourceMutationPlan,
    ResourceUpdated,
    run_after_commit_hooks,
    run_mutation_hooks,
)
from rakit_core.operations import current_operation_context
from rakit_core.transactions import TransactionPolicy
from sqlalchemy import select
from sqlalchemy import update as sqlalchemy_update
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
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
        resource_id: str | None = None,
        delete_nonce_store: IdempotencyStore | None = None,
        delete_permission: str | None = None,
        delete_relationship_impact: tuple[str, ...] = (),
        hooks: MutationHooks | None = None,
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
        self._event_publisher = event_publisher
        if (token_service is None) != (version_field is None):
            raise ValueError("token_service and version_field must be supplied together")
        self._version_field = version_field
        self._token_service = token_service
        self._resource_id = resource_id or str(getattr(model, "__tablename__", model.__name__))
        self._delete_nonce_store = delete_nonce_store
        self._delete_permission = delete_permission or f"resources.{self._resource_id}.delete"
        self._delete_relationship_impact = delete_relationship_impact
        self._hooks = hooks or MutationHooks()
        self._concurrency = (
            ConcurrencyTokenService(token_service) if token_service is not None else None
        )

    def bind_delete_nonce_store(self, store: IdempotencyStore) -> None:
        """Attach Admin's validated durable receipt store to delete confirmations."""
        self._delete_nonce_store = store

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

    async def create(self, submitted: Mapping[str, Any]) -> MutationResult:
        plan = self.prepare_create(submitted)
        try:
            await run_mutation_hooks(self._hooks.normalize, plan)
            await run_mutation_hooks(self._hooks.business_validate, plan)
            await run_mutation_hooks(self._hooks.prepare, plan)
            await run_mutation_hooks(self._hooks.authorize, plan)
            await run_mutation_hooks(self._hooks.pre_event, plan)
            await run_mutation_hooks(self._hooks.before_execute, plan)
            async with SQLAlchemyUnitOfWork(
                self._session_factory,
                policy=TransactionPolicy.AUTO,
                event_publisher=self._event_publisher,
                operation_context=current_operation_context(),
            ) as uow:
                record = self._model(**dict(plan.values))
                uow.session.add(record)
                await run_mutation_hooks(self._hooks.after_execute, plan)
                await uow.session.flush()
                await run_mutation_hooks(self._hooks.after_flush, plan)
                identity = self._identity_for(record)
                if self._event_publisher is not None:
                    self._event_publisher.publish(ResourceCreated(identity=identity))
                await run_mutation_hooks(self._hooks.before_commit, plan)
                await uow.mark_success()
        except BaseException as exc:
            await run_mutation_hooks(self._hooks.after_rollback, exc)
            raise
        result = MutationResult(identity=identity, record=record)
        await run_after_commit_hooks(self._hooks.after_commit, result)
        return result

    def issue_update_token(self, record: object) -> str:
        if self._concurrency is None or self._version_field is None:
            raise RuntimeError("This resource has no configured concurrency provider")
        return self._concurrency.issue(
            self._identity_for(record), getattr(record, self._version_field)
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
    ) -> MutationResult:
        plan = self.prepare_create(submitted)
        if set(identity.values) != set(self._identity_fields):
            raise RakitError(
                code=ErrorCode.VALIDATION_FAILED,
                message="Invalid resource identity",
                status_code=400,
            )
        try:
            await run_mutation_hooks(self._hooks.normalize, plan)
            await run_mutation_hooks(self._hooks.business_validate, plan)
            await run_mutation_hooks(self._hooks.prepare, plan)
            await run_mutation_hooks(self._hooks.authorize, plan)
            await run_mutation_hooks(self._hooks.pre_event, plan)
            await run_mutation_hooks(self._hooks.before_execute, plan)
            async with SQLAlchemyUnitOfWork(
                self._session_factory,
                policy=TransactionPolicy.AUTO,
                event_publisher=self._event_publisher,
                operation_context=current_operation_context(),
            ) as uow:
                record = await self._load(uow.session, identity)
                if record is None:
                    raise RakitError(
                        code=ErrorCode.RESOURCE_NOT_FOUND,
                        message="Resource was not found",
                        status_code=404,
                    )
                if self._concurrency is not None and self._version_field is not None:
                    if not concurrency_token:
                        raise RakitError(
                            code=ErrorCode.RESOURCE_CONFLICT,
                            message="A concurrency token is required.",
                            status_code=409,
                        )
                    self._concurrency.verify(
                        concurrency_token, identity, getattr(record, self._version_field)
                    )
                    current_version = getattr(record, self._version_field)
                    if not isinstance(current_version, int):
                        raise RuntimeError("Configured version field must contain an integer")
                    # The in-memory token check above makes stale forms pleasant
                    # to reject, but it cannot protect two independent database
                    # transactions that both read the same revision.  Put the
                    # expected revision in the UPDATE predicate as well: exactly
                    # one of concurrent writers can affect a row.
                    result = cast(
                        CursorResult[Any],
                        await uow.session.execute(
                            sqlalchemy_update(self._model)
                            .where(
                                *self._identity_conditions(identity),
                                getattr(self._model, self._version_field) == current_version,
                            )
                            .values(
                                **dict(plan.values),
                                **{self._version_field: current_version + 1},
                            )
                        ),
                    )
                    await run_mutation_hooks(self._hooks.after_execute, plan)
                    if result.rowcount != 1:
                        raise RakitError(
                            code=ErrorCode.RESOURCE_CONFLICT,
                            message="The resource was changed by another request.",
                            status_code=409,
                        )
                    await uow.session.refresh(record)
                else:
                    for name, value in plan.values.items():
                        setattr(record, name, value)
                    await uow.session.flush()
                    await run_mutation_hooks(self._hooks.after_execute, plan)
                await run_mutation_hooks(self._hooks.after_flush, plan)
                if self._event_publisher is not None:
                    self._event_publisher.publish(
                        ResourceUpdated(identity=identity, changed_fields=tuple(plan.values))
                    )
                await run_mutation_hooks(self._hooks.before_commit, plan)
                await uow.mark_success()
        except BaseException as exc:
            await run_mutation_hooks(self._hooks.after_rollback, exc)
            raise
        mutation_result = MutationResult(identity=identity, record=record)
        await run_after_commit_hooks(self._hooks.after_commit, mutation_result)
        return mutation_result

    async def preview_delete(self, identity: RecordIdentity) -> DeletionPlan:
        if self._token_service is None or self._version_field is None:
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
                expected_version=getattr(record, self._version_field),
                relationship_impact=self._delete_relationship_impact,
                required_permission=self._delete_permission,
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
        self, confirmation_token: str, *, identity: RecordIdentity | None = None
    ) -> None:
        if self._token_service is None or self._version_field is None:
            raise RuntimeError("Delete requires a configured token and version provider")
        if self._delete_nonce_store is None:
            raise RakitError(
                code=ErrorCode.CONFIG_INVALID,
                message="Delete requires a durable confirmation store.",
                status_code=500,
            )
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
            if claims.get("resource_id") != self._resource_id or set(
                confirmed_identity.values
            ) != set(self._identity_fields) or (
                relationship_impact != self._delete_relationship_impact
                or required_permission != self._delete_permission
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
            await run_mutation_hooks(self._hooks.before_execute, confirmed_identity)
            async with SQLAlchemyUnitOfWork(
                self._session_factory,
                policy=TransactionPolicy.AUTO,
                event_publisher=self._event_publisher,
                operation_context=current_operation_context(),
            ) as uow:
                record = await self._load(uow.session, confirmed_identity)
                if record is None:
                    raise RakitError(
                        code=ErrorCode.RESOURCE_NOT_FOUND,
                        message="Resource was not found",
                        status_code=404,
                    )
                if getattr(record, self._version_field) != expected_version:
                    raise RakitError(
                        code=ErrorCode.RESOURCE_CONFLICT,
                        message="The resource has changed since deletion was confirmed.",
                        status_code=409,
                    )
                await uow.session.delete(record)
                await uow.session.flush()
                if self._event_publisher is not None:
                    self._event_publisher.publish(ResourceDeleted(identity=confirmed_identity))
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
            await session.scalars(select(self._model).where(*self._identity_conditions(identity)))
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


__all__ = [
    "ResourceCreated",
    "ResourceDeleted",
    "ResourceUpdated",
    "SQLAlchemyMutationService",
]
