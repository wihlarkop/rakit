from __future__ import annotations

from typing import Any, Self

import anyio
from playhouse.pwasyncio import AsyncDatabaseMixin
from rakit_core.events import EventPublisher
from rakit_core.operations import OperationContext
from rakit_core.transactions import TransactionPolicy


class _RollbackOnly(RuntimeError):
    pass


class PeeweeOperationUnitOfWorkFactory:
    def __init__(self, *, database: AsyncDatabaseMixin) -> None:
        self._database = database

    def open(
        self,
        *,
        policy: TransactionPolicy,
        event_publisher: EventPublisher | None,
        operation_context: OperationContext,
    ) -> PeeweeUnitOfWork:
        return PeeweeUnitOfWork(
            database=self._database,
            policy=policy,
            event_publisher=event_publisher,
            operation_context=operation_context,
        )


class PeeweeUnitOfWork:
    def __init__(
        self,
        *,
        database: AsyncDatabaseMixin,
        policy: TransactionPolicy,
        event_publisher: EventPublisher | None = None,
        operation_context: OperationContext | None = None,
    ) -> None:
        self.database = database
        self.policy = policy
        self.event_publisher = event_publisher
        self.operation_context = operation_context
        self._atomic: Any | None = None
        self._database_entered = False
        self._success = False
        self._completed = False
        self._rollback_cause: BaseException | None = None

    async def __aenter__(self) -> Self:
        if self.policy is TransactionPolicy.DISABLED:
            raise RuntimeError("Peewee root UoW is only used for transactional operations")
        await self.database.__aenter__()
        self._database_entered = True
        atomic = self.database.atomic()
        try:
            await atomic.__aenter__()
        except BaseException as exc:
            await self.database.__aexit__(type(exc), exc, exc.__traceback__)
            self._database_entered = False
            raise
        self._atomic = atomic
        return self

    async def mark_success(self) -> None:
        if self.operation_context is not None:
            self.operation_context.checkpoint()
        self._success = True

    async def _close_context(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: object,
    ) -> None:
        atomic = self._atomic
        if atomic is None:
            return
        try:
            await atomic.__aexit__(exc_type, exc, traceback)
        except BaseException as finish_exc:
            if self._database_entered:
                await self.database.__aexit__(
                    type(finish_exc), finish_exc, finish_exc.__traceback__
                )
            raise
        else:
            if self._database_entered:
                await self.database.__aexit__(None, None, None)
        finally:
            self._atomic = None
            self._database_entered = False

    async def _finish_context(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: object,
        *,
        shield: bool,
    ) -> None:
        if shield:
            with anyio.CancelScope(shield=True):
                await self._close_context(exc_type, exc, traceback)
        else:
            await self._close_context(exc_type, exc, traceback)

    async def _dispatch_post_commit_events(self) -> None:
        if self.event_publisher is None:
            return
        context = self.operation_context
        detach = context is not None and context.unit_of_work is self
        if detach:
            object.__setattr__(context, "unit_of_work", None)
        try:
            await self.event_publisher.after_commit()
        finally:
            if detach:
                object.__setattr__(context, "unit_of_work", self)

    async def _finish_commit(self) -> None:
        await self._finish_context(None, None, None, shield=True)
        if self.operation_context is not None:
            self.operation_context.mark_durable_commit_completed()
        self._completed = True
        await self._dispatch_post_commit_events()

    async def commit(self) -> None:
        if self.policy is not TransactionPolicy.MANUAL:
            raise RuntimeError("Explicit commit is only available with manual transaction policy")
        if self._completed:
            raise RuntimeError("Unit of work has already completed")
        if self.operation_context is not None:
            self.operation_context.checkpoint()
        await self._finish_commit()

    async def rollback(self, cause: BaseException | None = None) -> None:
        if cause is not None and self._rollback_cause is None:
            self._rollback_cause = cause
        if self._completed:
            return
        rollback_cause = cause or _RollbackOnly("Peewee root unit of work rolled back")
        await self._finish_context(
            type(rollback_cause),
            rollback_cause,
            rollback_cause.__traceback__,
            shield=True,
        )
        self._completed = True
        if self.event_publisher is not None:
            self.event_publisher.after_rollback()

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: object,
    ) -> bool:
        if exc_type is not None:
            await self.rollback(exc)
        elif self.policy is TransactionPolicy.AUTO and self._success:
            if self.operation_context is not None:
                self.operation_context.checkpoint()
            await self._finish_commit()
        elif not self._completed:
            await self.rollback()
        return False


__all__ = ["PeeweeOperationUnitOfWorkFactory", "PeeweeUnitOfWork"]
