from __future__ import annotations

from typing import Any, Self

import anyio
from piccolo.engine.base import Engine
from rakit_core.events import EventPublisher
from rakit_core.operations import OperationContext
from rakit_core.transactions import TransactionPolicy


class PiccoloOperationUnitOfWorkFactory:
    def __init__(self, *, engine: Engine[Any]) -> None:
        self._engine = engine

    def open(
        self,
        *,
        policy: TransactionPolicy,
        event_publisher: EventPublisher | None,
        operation_context: OperationContext,
    ) -> PiccoloUnitOfWork:
        return PiccoloUnitOfWork(
            engine=self._engine,
            policy=policy,
            event_publisher=event_publisher,
            operation_context=operation_context,
        )


class PiccoloUnitOfWork:
    def __init__(
        self,
        *,
        engine: Engine[Any],
        policy: TransactionPolicy,
        event_publisher: EventPublisher | None = None,
        operation_context: OperationContext | None = None,
    ) -> None:
        self.engine = engine
        self.policy = policy
        self.event_publisher = event_publisher
        self.operation_context = operation_context
        self._transaction: Any | None = None
        self._success = False
        self._completed = False
        self._rollback_cause: BaseException | None = None

    async def __aenter__(self) -> Self:
        if self.policy is TransactionPolicy.DISABLED:
            raise RuntimeError("Piccolo root UoW is only used for transactional operations")
        if self.engine.transaction_exists():
            raise RuntimeError("Piccolo root UoW requires ownership of the root transaction")
        transaction = self.engine.transaction(allow_nested=False)
        await transaction.__aenter__()
        self._transaction = transaction
        return self

    async def mark_success(self) -> None:
        if self.operation_context is not None:
            self.operation_context.checkpoint()
        self._success = True

    async def _close_context(self) -> None:
        transaction = self._transaction
        if transaction is None:
            return
        try:
            await transaction.__aexit__(None, None, None)
        finally:
            self._transaction = None

    async def _finish_context(self, *, shield: bool) -> None:
        if shield:
            with anyio.CancelScope(shield=True):
                await self._close_context()
        else:
            await self._close_context()

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
        transaction = self._transaction
        if transaction is None:
            raise RuntimeError("Piccolo transaction is not active")
        with anyio.CancelScope(shield=True):
            await transaction.commit()
            await self._close_context()
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
        transaction = self._transaction
        if transaction is None:
            self._completed = True
            return
        with anyio.CancelScope(shield=True):
            await transaction.rollback()
            await self._close_context()
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


__all__ = ["PiccoloOperationUnitOfWorkFactory", "PiccoloUnitOfWork"]
