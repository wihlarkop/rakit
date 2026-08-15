"""Operation-scoped SQLAlchemy transaction handling."""

import asyncio
import inspect
from collections.abc import Awaitable, Callable
from contextvars import ContextVar, Token
from typing import Self

import anyio
from rakit_core.events import EventPublisher
from rakit_core.operations import OperationContext
from rakit_core.transactions import TransactionPolicy
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

_active_uow: ContextVar["SQLAlchemyUnitOfWork | None"] = ContextVar(
    "rakit_active_sqlalchemy_uow", default=None
)


class SQLAlchemyOperationUnitOfWorkFactory:
    """Adapter implementing the backend-neutral ``OperationUnitOfWorkFactory``.

    Opens the existing ``SQLAlchemyUnitOfWork`` over the exact session factory
    installed by ``SQLAlchemyPlugin`` -- there is deliberately only one
    session factory per admin.
    """

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    def open(
        self,
        *,
        policy: TransactionPolicy,
        event_publisher: EventPublisher | None,
        operation_context: OperationContext,
    ) -> "SQLAlchemyUnitOfWork":
        return SQLAlchemyUnitOfWork(
            self._session_factory,
            policy=policy,
            event_publisher=event_publisher,
            operation_context=operation_context,
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
        self._before_commit_callbacks: list[Callable[[], object | Awaitable[object]]] = []
        self._after_commit_callbacks: list[Callable[[], object | Awaitable[object]]] = []
        self._after_commit_observer_callbacks: list[Callable[[], object | Awaitable[object]]] = []
        self._after_rollback_callbacks: list[Callable[[], object | Awaitable[object]]] = []
        self._after_rollback_observer_callbacks: list[Callable[[], object | Awaitable[object]]] = []
        self._commit_observers_ready = False
        self._rollback_observers_ready = False
        self._rollback_cause: BaseException | None = None

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

    def after_commit(self, callback: Callable[[], object | Awaitable[object]]) -> None:
        """Run a callback only after the root operation transaction commits."""

        if self._parent is not None:
            self._parent.after_commit(callback)
            return
        self._after_commit_callbacks.append(callback)

    def before_commit(self, callback: Callable[[], object | Awaitable[object]]) -> None:
        """Run a root-owned lifecycle callback before the durable commit."""

        if self._parent is not None:
            self._parent.before_commit(callback)
            return
        self._before_commit_callbacks.append(callback)

    def after_commit_observer(self, callback: Callable[[], object | Awaitable[object]]) -> None:
        """Run a resource observer after deferred post-commit events.

        Transaction bookkeeping belongs in :meth:`after_commit`; resource
        lifecycle observers need the same externally-visible order as an
        ordinary mutation: durable commit, deferred event delivery, observer.
        """

        if self._parent is not None:
            self._parent.after_commit_observer(callback)
            return
        self._after_commit_observer_callbacks.append(callback)

    @property
    def rollback_cause(self) -> BaseException | None:
        """The root failure available to deferred nested rollback hooks."""

        return self._rollback_cause

    def after_rollback(self, callback: Callable[[], object | Awaitable[object]]) -> None:
        if self._parent is not None:
            self._parent.after_rollback(callback)
            return
        self._after_rollback_callbacks.append(callback)

    def after_rollback_observer(self, callback: Callable[[], object | Awaitable[object]]) -> None:
        """Run a resource rollback observer after deferred events are discarded."""

        if self._parent is not None:
            self._parent.after_rollback_observer(callback)
            return
        self._after_rollback_observer_callbacks.append(callback)

    async def _run_callbacks(
        self, callbacks: list[Callable[[], object | Awaitable[object]]]
    ) -> None:
        while callbacks:
            result = callbacks.pop(0)()
            if inspect.isawaitable(result):
                await result

    async def commit(self) -> None:
        if self._parent is not None:
            raise RuntimeError("Nested unit of work cannot commit its parent transaction")
        if self.policy is not TransactionPolicy.MANUAL:
            raise RuntimeError("Explicit commit is only available with manual transaction policy")
        await self._run_callbacks(self._before_commit_callbacks)
        await self._commit_critical()
        self._completed = True
        await self._finish_commit_callbacks()

    async def rollback(self, cause: BaseException | None = None) -> None:
        if cause is not None and self._rollback_cause is None:
            self._rollback_cause = cause
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
        await self._finish_rollback_callbacks()

    async def _dispatch_post_commit_events(self) -> None:
        """Deliver deferred events without exposing this completed UoW to handlers.

        Transaction bookkeeping deliberately remains in the active root UoW,
        including for explicit MANUAL commits.  Event handlers are post-commit
        application work, though, and may start another SQLAlchemy operation.
        Temporarily clearing both the SQLAlchemy ContextVar and the generic
        ``OperationContext.unit_of_work`` reference lets that work own a fresh
        UoW/session while preserving the surrounding root UoW's teardown and
        public MANUAL timing.
        """

        if self.event_publisher is None:
            return
        operation_context = self.operation_context
        detach_operation_uow = (
            operation_context is not None and operation_context.unit_of_work is self
        )
        if detach_operation_uow:
            object.__setattr__(operation_context, "unit_of_work", None)
        try:
            if _active_uow.get() is not self:
                await self.event_publisher.after_commit()
                return
            token = _active_uow.set(None)
            try:
                await self.event_publisher.after_commit()
            finally:
                _active_uow.reset(token)
        finally:
            if detach_operation_uow:
                object.__setattr__(operation_context, "unit_of_work", self)

    async def _finish_commit_callbacks(self) -> None:
        """Finish durable bookkeeping, then dispatch post-commit events safely."""

        await self._run_callbacks(self._after_commit_callbacks)
        await self._dispatch_post_commit_events()
        self._commit_observers_ready = True

    async def _finish_rollback_callbacks(self) -> None:
        """Finish rollback bookkeeping and discard deferred events inside the root UoW."""

        await self._run_callbacks(self._after_rollback_callbacks)
        if self.event_publisher is not None:
            self.event_publisher.after_rollback()
        self._rollback_observers_ready = True

    async def _run_resource_observers_after_teardown(self) -> None:
        """Run resource lifecycle observers with no completed UoW in context."""

        if self._commit_observers_ready:
            self._commit_observers_ready = False
            await self._run_callbacks(self._after_commit_observer_callbacks)
        if self._rollback_observers_ready:
            self._rollback_observers_ready = False
            await self._run_callbacks(self._after_rollback_observer_callbacks)

    async def _commit_critical(self) -> None:
        """Finish the durable commit once it has started, despite cancellation.

        Cancellation remains cooperative until the checkpoint immediately
        before this method.  After the driver is asked to commit, awaiting a
        cancelled request must not let the caller report a rollback while the
        database task continues and commits in the background.
        """
        commit_task = asyncio.create_task(self.session.commit())
        try:
            with anyio.CancelScope(shield=True):
                await asyncio.shield(commit_task)
        except asyncio.CancelledError:
            with anyio.CancelScope(shield=True):
                await asyncio.shield(commit_task)

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: object,
    ) -> bool:
        try:
            try:
                if self._parent is not None:
                    if exc_type is not None:
                        await self.rollback(exc)
                    elif self._savepoint is not None:
                        commit = getattr(self._savepoint, "commit", None)
                        if callable(commit):
                            await commit()
                        self._completed = True
                    # An inherited child never owns commit/close of its parent.
                elif exc_type is not None:
                    await self.rollback(exc)
                elif self.policy is TransactionPolicy.AUTO and self._success and not self._failed:
                    try:
                        if self.operation_context is not None:
                            # A commit already in progress is never force-cancelled;
                            # this is the last cooperative checkpoint before it starts.
                            self.operation_context.checkpoint()
                        await self._run_callbacks(self._before_commit_callbacks)
                        await self._commit_critical()
                    except BaseException as exc:
                        # A deadline or driver failure before the durable outcome
                        # is known must leave the session in a safe rolled-back
                        # state.  `_commit_critical` only returns after a started
                        # commit has finished, so this cannot roll back a commit
                        # that completed while cancellation was pending.
                        await self.rollback(exc)
                        raise
                    self._completed = True
                    await self._finish_commit_callbacks()
                elif self.policy is TransactionPolicy.DISABLED and self._success:
                    self._completed = True
                    await self._finish_commit_callbacks()
                elif not self._completed:
                    await self.rollback()
            finally:
                if self._context_token is not None:
                    _active_uow.reset(self._context_token)
                if self._parent is None:
                    await self.session.close()
        finally:
            # Resource observers intentionally run outside the finished root
            # UoW.  Their post-transaction work must start a fresh operation,
            # never inherit a completed session through `_active_uow`.
            await self._run_resource_observers_after_teardown()
        return False
