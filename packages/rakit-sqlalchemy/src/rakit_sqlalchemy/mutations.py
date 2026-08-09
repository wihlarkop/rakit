"""SQLAlchemy execution for the framework-neutral write pipeline."""

from collections.abc import Mapping
from typing import Any

from rakit_core.concurrency import ConcurrencyTokenService
from rakit_core.crypto import TokenService
from rakit_core.errors import ErrorCode, RakitError
from rakit_core.events import EventPublisher
from rakit_core.forms import FormSchema, FormValidationError
from rakit_core.identity import RecordIdentity
from rakit_core.mutations import (
    MutationResult,
    ResourceCreated,
    ResourceMutationPlan,
    ResourceUpdated,
)
from rakit_core.transactions import TransactionPolicy
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

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
        self._concurrency = (
            ConcurrencyTokenService(token_service) if token_service is not None else None
        )

    def prepare_create(self, submitted: Mapping[str, Any]) -> ResourceMutationPlan:
        try:
            state = self._form_schema.parse(submitted)
        except (FormValidationError, ValueError) as exc:
            raise _validation_error(exc) from exc
        values = dict(state.normalized)
        if not set(values).issubset(self._writable_fields):
            raise _validation_error(ValueError("Field is not writable"))
        return ResourceMutationPlan(operation="create", values=values)

    async def create(self, submitted: Mapping[str, Any]) -> MutationResult:
        plan = self.prepare_create(submitted)
        async with SQLAlchemyUnitOfWork(
            self._session_factory,
            policy=TransactionPolicy.AUTO,
            event_publisher=self._event_publisher,
        ) as uow:
            record = self._model(**dict(plan.values))
            uow.session.add(record)
            await uow.session.flush()
            identity = self._identity_for(record)
            if self._event_publisher is not None:
                self._event_publisher.publish(ResourceCreated(identity=identity))
            await uow.mark_success()
        return MutationResult(identity=identity, record=record)

    def issue_update_token(self, record: object) -> str:
        if self._concurrency is None or self._version_field is None:
            raise RuntimeError("This resource has no configured concurrency provider")
        return self._concurrency.issue(
            self._identity_for(record), getattr(record, self._version_field)
        )

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
        async with SQLAlchemyUnitOfWork(
            self._session_factory,
            policy=TransactionPolicy.AUTO,
            event_publisher=self._event_publisher,
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
            for name, value in plan.values.items():
                setattr(record, name, value)
            if self._version_field is not None:
                current_version = getattr(record, self._version_field)
                if not isinstance(current_version, int):
                    raise RuntimeError("Configured version field must contain an integer")
                setattr(record, self._version_field, current_version + 1)
            await uow.session.flush()
            if self._event_publisher is not None:
                self._event_publisher.publish(
                    ResourceUpdated(identity=identity, changed_fields=tuple(plan.values))
                )
            await uow.mark_success()
        return MutationResult(identity=identity, record=record)

    async def _load(self, session: AsyncSession, identity: RecordIdentity) -> object | None:
        conditions = [
            getattr(self._model, name) == value for name, value in identity.values.items()
        ]
        return (await session.scalars(select(self._model).where(*conditions))).one_or_none()

    def _identity_for(self, record: object) -> RecordIdentity:
        return RecordIdentity(
            values={name: getattr(record, name) for name in self._identity_fields}
        )


__all__ = [
    "ResourceCreated",
    "ResourceUpdated",
    "SQLAlchemyMutationService",
]
