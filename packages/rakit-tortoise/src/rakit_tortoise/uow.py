from __future__ import annotations

import asyncio
from typing import Self

import anyio
from rakit_core.events import EventPublisher
from rakit_core.operations import OperationContext
from rakit_core.transactions import TransactionPolicy
from tortoise.backends.base.client import TransactionalDBClient
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
        self.connection: TransactionalDBClient
        self._success = False
        self._completed = False
        self._rollback_cause: BaseException | None = None
        self._connection_ready: asyncio.Future[TransactionalDBClient] | None = None
        self._commit_outcome: asyncio.Future[bool] | None = None
        self._owner_task: asyncio.Task[None] | None = None

    async def _transaction_owner(self) -> None:
        assert self._connection_ready is not None
        assert self._commit_outcome is not None
        try:
            async with in_transaction(self.connection_name) as connection:
                self._connection_ready.set_result(connection)
                should_commit = await self._commit_outcome
                if not should_commit:
                    await connection.rollback()
        except BaseException as exc:
            if not self._connection_ready.done():
                self._connection_ready.set_exception(exc)
            raise

    async def __aenter__(self) -> Self:
        if self.policy is TransactionPolicy.DISABLED:
            raise RuntimeError("Tortoise root UoW is only used for transactional operations")
        loop = asyncio.get_running_loop()
        self._connection_ready = loop.create_future()
        self._commit_outcome = loop.create_future()
        self._owner_task = asyncio.create_task(self._transaction_owner())
        self.connection = await self._connection_ready
        return self

    async def mark_success(self) -> None:
        if self.operation_context is not None:
            self.operation_context.checkpoint()
        self._success = True

    async def _finish_owner(self, *, commit: bool, shield: bool) -> None:
        outcome = self._commit_outcome
        owner_task = self._owner_task
        if outcome is None or owner_task is None:
            return
        if not outcome.done():
            outcome.set_result(commit)
        if shield:
            try:
                with anyio.CancelScope(shield=True):
                    await asyncio.shield(owner_task)
            except asyncio.CancelledError:
                with anyio.CancelScope(shield=True):
                    await asyncio.shield(owner_task)
        else:
            await owner_task
        self._owner_task = None

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
        await self._finish_owner(commit=True, shield=True)
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
        await self._finish_owner(commit=False, shield=True)
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
        if exc_type is not None:
            await self.rollback(exc)
        elif self.policy is TransactionPolicy.AUTO and self._success:
            if self.operation_context is not None:
                self.operation_context.checkpoint()
            await self._finish_commit()
        elif not self._completed:
            await self.rollback()
        return False


__all__ = ["TortoiseOperationUnitOfWorkFactory", "TortoiseUnitOfWork"]
