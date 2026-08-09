"""Operation-scoped SQLAlchemy transaction handling."""

from typing import Self

from rakit_core.events import EventPublisher
from rakit_core.operations import OperationContext
from rakit_core.transactions import TransactionPolicy
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


class SQLAlchemyUnitOfWork:
    """Own one session and commit only after an explicitly successful operation."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        *,
        policy: TransactionPolicy = TransactionPolicy.AUTO,
        event_publisher: EventPublisher | None = None,
        operation_context: OperationContext | None = None,
    ) -> None:
        self._session_factory = session_factory
        self.policy = policy
        self.event_publisher = event_publisher
        self.operation_context = operation_context
        self.session: AsyncSession
        self._success = False
        self._completed = False

    async def __aenter__(self) -> Self:
        self.session = self._session_factory()
        return self

    async def mark_success(self) -> None:
        if self.operation_context is not None:
            self.operation_context.checkpoint()
        self._success = True

    async def commit(self) -> None:
        if self.policy is not TransactionPolicy.MANUAL:
            raise RuntimeError("Explicit commit is only available with manual transaction policy")
        await self.session.commit()
        self._completed = True
        if self.event_publisher is not None:
            await self.event_publisher.after_commit()

    async def rollback(self) -> None:
        await self.session.rollback()
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
                await self.rollback()
            elif self.policy is TransactionPolicy.AUTO and self._success:
                if self.operation_context is not None:
                    # A commit already in progress is never force-cancelled;
                    # this is the last cooperative checkpoint before it starts.
                    self.operation_context.checkpoint()
                await self.session.commit()
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
            await self.session.close()
        return False
