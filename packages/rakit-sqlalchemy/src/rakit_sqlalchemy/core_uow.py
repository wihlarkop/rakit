from __future__ import annotations

import asyncio
from typing import Self

import anyio
from rakit_core.events import EventPublisher
from rakit_core.operations import OperationContext
from rakit_core.transactions import TransactionPolicy
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, AsyncTransaction


class SQLAlchemyCoreOperationUnitOfWorkFactory:
    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    def open(
        self,
        *,
        policy: TransactionPolicy,
        event_publisher: EventPublisher | None,
        operation_context: OperationContext,
    ) -> SQLAlchemyCoreUnitOfWork:
        return SQLAlchemyCoreUnitOfWork(
            self._engine,
            policy=policy,
            event_publisher=event_publisher,
            operation_context=operation_context,
        )


class SQLAlchemyCoreUnitOfWork:
    def __init__(
        self,
        engine: AsyncEngine,
        *,
        policy: TransactionPolicy,
        event_publisher: EventPublisher | None = None,
        operation_context: OperationContext | None = None,
    ) -> None:
        self._engine = engine
        self.policy = policy
        self.event_publisher = event_publisher
        self.operation_context = operation_context
        self.connection: AsyncConnection
        self._transaction: AsyncTransaction | None = None
        self._success = False
        self._completed = False
        self._rollback_cause: BaseException | None = None

    async def __aenter__(self) -> Self:
        self.connection = await self._engine.connect()
        if self.policy is not TransactionPolicy.DISABLED:
            self._transaction = await self.connection.begin()
        return self

    async def mark_success(self) -> None:
        if self.operation_context is not None:
            self.operation_context.checkpoint()
        self._success = True

    async def _commit_critical(self) -> None:
        transaction = self._transaction
        if transaction is None:
            return
        commit_task = asyncio.create_task(transaction.commit())
        try:
            with anyio.CancelScope(shield=True):
                await asyncio.shield(commit_task)
        except asyncio.CancelledError:
            with anyio.CancelScope(shield=True):
                await asyncio.shield(commit_task)

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
        await self._commit_critical()
        if self.operation_context is not None:
            self.operation_context.mark_durable_commit_completed()
        self._completed = True
        await self._dispatch_post_commit_events()

    async def commit(self) -> None:
        if self.policy is not TransactionPolicy.MANUAL:
            raise RuntimeError("Explicit commit is only available with manual transaction policy")
        if self._completed:
            raise RuntimeError("Unit of work has already completed")
        await self._finish_commit()

    async def rollback(self, cause: BaseException | None = None) -> None:
        if cause is not None and self._rollback_cause is None:
            self._rollback_cause = cause
        if self._completed:
            return
        transaction = self._transaction
        if transaction is not None and transaction.is_active:
            await transaction.rollback()
        self._completed = True
        if self.event_publisher is not None:
            self.event_publisher.after_rollback()

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: object,
    ) -> bool:
        del traceback
        try:
            if exc_type is not None:
                await self.rollback(exc)
            elif self.policy is TransactionPolicy.AUTO and self._success:
                if self.operation_context is not None:
                    self.operation_context.checkpoint()
                await self._finish_commit()
            elif self.policy is TransactionPolicy.DISABLED and self._success:
                self._completed = True
                if self.operation_context is not None:
                    self.operation_context.mark_durable_commit_completed()
                await self._dispatch_post_commit_events()
            elif not self._completed:
                await self.rollback()
        finally:
            await self.connection.close()
        return False


__all__ = [
    "SQLAlchemyCoreOperationUnitOfWorkFactory",
    "SQLAlchemyCoreUnitOfWork",
]
