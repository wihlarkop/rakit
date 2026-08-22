from __future__ import annotations

import asyncio
from typing import Any, Self

import anyio
from rakit_core.events import EventPublisher
from rakit_core.operations import OperationContext
from rakit_core.transactions import TransactionPolicy
from tortoise.backends.base.client import BaseDBAsyncClient
from tortoise.transactions import in_transaction


class TortoiseOperationUnitOfWorkFactory:
    def __init__(self, *, connection_name: str = "default") -> None:
        if not connection_name or connection_name != connection_name.strip():
            raise ValueError("connection_name must be a non-empty normalized string")
        self._connection_name = connection_name

    def open(
        self,
        *,
        policy: TransactionPolicy,
        event_publisher: EventPublisher | None,
        operation_context: OperationContext,
    ) -> TortoiseUnitOfWork:
        return TortoiseUnitOfWork(
            connection_name=self._connection_name,
            policy=policy,
            event_publisher=event_publisher,
            operation_context=operation_context,
        )


class TortoiseUnitOfWork:
    def __init__(
        self,
        *,
        connection_name: str,
        policy: TransactionPolicy,
        event_publisher: EventPublisher | None = None,
        operation_context: OperationContext | None = None,
    ) -> None:
        self.connection_name = connection_name
        self.policy = policy
        self.event_publisher = event_publisher
        self.operation_context = operation_context
        self.connection: BaseDBAsyncClient
        self._transaction_context: Any = None
        self._success = False
        self._completed = False
        self._rollback_cause: BaseException | None = None

    async def __aenter__(self) -> Self:
        if self.policy is TransactionPolicy.DISABLED:
            raise RuntimeError("Tortoise root UoW is only used for transactional operations")
        self._transaction_context = in_transaction(self.connection_name)
        self.connection = await self._transaction_context.__aenter__()
        return self

    async def mark_success(self) -> None:
        if self.operation_context is not None:
            self.operation_context.checkpoint()
        self._success = True

    async def _commit_context_critical(self) -> None:
        transaction_context = self._transaction_context
        if transaction_context is None:
            return
        commit_task = asyncio.create_task(transaction_context.__aexit__(None, None, None))
        try:
            with anyio.CancelScope(shield=True):
                await asyncio.shield(commit_task)
        except asyncio.CancelledError:
            with anyio.CancelScope(shield=True):
                await asyncio.shield(commit_task)
        self._transaction_context = None

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
        await self._commit_context_critical()
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

        transaction_context = self._transaction_context
        connection = self.connection
        if transaction_context is not None:
            if cause is not None:
                await transaction_context.__aexit__(type(cause), cause, cause.__traceback__)
            else:
                await connection.rollback()
                await transaction_context.__aexit__(None, None, None)
            self._transaction_context = None

        self._completed = True
        if self.event_publisher is not None:
            self.event_publisher.after_rollback()

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: object,
    ) -> bool:
        try:
            if exc_type is not None:
                await self.rollback(exc)
            elif self.policy is TransactionPolicy.AUTO and self._success:
                if self.operation_context is not None:
                    self.operation_context.checkpoint()
                await self._finish_commit()
            elif not self._completed:
                await self.rollback()
        finally:
            transaction_context = self._transaction_context
            if transaction_context is not None:
                await transaction_context.__aexit__(exc_type, exc, traceback)
                self._transaction_context = None
        return False


__all__ = ["TortoiseOperationUnitOfWorkFactory", "TortoiseUnitOfWork"]
