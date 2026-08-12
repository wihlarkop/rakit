"""Operation-scoped SQLAlchemy transaction handling."""

import asyncio
from contextvars import ContextVar, Token
from typing import Self

from rakit_core.events import EventPublisher
from rakit_core.operations import OperationContext
from rakit_core.transactions import TransactionPolicy
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

_active_uow: ContextVar["SQLAlchemyUnitOfWork | None"] = ContextVar(
    "rakit_active_sqlalchemy_uow", default=None
)


class SQLAlchemyUnitOfWork:
    """Own one session and commit only after an explicitly successful operation."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        *,
        policy: TransactionPolicy = TransactionPolicy.AUTO,
        event_publisher: EventPublisher | None = None,
        operation_context: OperationContext | None = None,
        savepoint: bool = False,
    ) -> None:
        self._session_factory = session_factory
        self.policy = policy
        self.event_publisher = event_publisher
        self.operation_context = operation_context
        self._savepoint_requested = savepoint
        self.session: AsyncSession
        self._success = False
        self._failed = False
        self._completed = False
        self._parent: SQLAlchemyUnitOfWork | None = None
        self._savepoint: object | None = None
        self._context_token: Token[SQLAlchemyUnitOfWork | None] | None = None

    async def __aenter__(self) -> Self:
        active = _active_uow.get()
        if active is not None:
            self._parent = active
            self.session = active.session
            if self._savepoint_requested:
                begin_nested = getattr(self.session, "begin_nested", None)
                if not callable(begin_nested):
                    raise RuntimeError("The active transaction does not support savepoints")
                self._savepoint = await begin_nested()
        elif self._savepoint_requested:
            raise RuntimeError("A savepoint requires an active parent unit of work")
        else:
            self.session = self._session_factory()
        self._context_token = _active_uow.set(self)
        return self

    async def mark_success(self) -> None:
        if self.operation_context is not None:
            self.operation_context.checkpoint()
        if not self._failed:
            self._success = True

    async def commit(self) -> None:
        if self._parent is not None:
            raise RuntimeError("Nested unit of work cannot commit its parent transaction")
        if self.policy is not TransactionPolicy.MANUAL:
            raise RuntimeError("Explicit commit is only available with manual transaction policy")
        await self._commit_critical()
        self._completed = True
        if self.event_publisher is not None:
            await self.event_publisher.after_commit()

    async def rollback(self) -> None:
        if self._parent is not None and self._savepoint is not None:
            rollback = getattr(self._savepoint, "rollback", None)
            if callable(rollback):
                await rollback()
            self._completed = True
            return
        if self._parent is not None:
            self._parent._failed = True
            self._parent._success = False
            self._completed = True
            return
        await self.session.rollback()
        self._completed = True
        if self.event_publisher is not None:
            self.event_publisher.after_rollback()

    async def _commit_critical(self) -> None:
        """Finish the durable commit once it has started, despite cancellation.

        Cancellation remains cooperative until the checkpoint immediately
        before this method.  After the driver is asked to commit, awaiting a
        cancelled request must not let the caller report a rollback while the
        database task continues and commits in the background.
        """
        commit_task = asyncio.create_task(self.session.commit())
        try:
            await asyncio.shield(commit_task)
        except asyncio.CancelledError:
            await asyncio.shield(commit_task)

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: object,
    ) -> bool:
        try:
            if self._parent is not None:
                if exc_type is not None:
                    await self.rollback()
                elif self._savepoint is not None:
                    commit = getattr(self._savepoint, "commit", None)
                    if callable(commit):
                        await commit()
                    self._completed = True
                # An inherited child never owns commit/close of its parent.
            elif exc_type is not None:
                await self.rollback()
            elif self.policy is TransactionPolicy.AUTO and self._success and not self._failed:
                try:
                    if self.operation_context is not None:
                        # A commit already in progress is never force-cancelled;
                        # this is the last cooperative checkpoint before it starts.
                        self.operation_context.checkpoint()
                    await self._commit_critical()
                except BaseException:
                    # A deadline or driver failure before the durable outcome
                    # is known must leave the session in a safe rolled-back
                    # state.  `_commit_critical` only returns after a started
                    # commit has finished, so this cannot roll back a commit
                    # that completed while cancellation was pending.
                    await self.rollback()
                    raise
                self._completed = True
                if self.event_publisher is not None:
                    await self.event_publisher.after_commit()
            elif self.policy is TransactionPolicy.DISABLED and self._success:
                self._completed = True
                if self.event_publisher is not None:
                    await self.event_publisher.after_commit()
            elif not self._completed:
                await self.rollback()
        finally:
            if self._context_token is not None:
                _active_uow.reset(self._context_token)
            if self._parent is None:
                await self.session.close()
        return False
