import asyncio
from collections.abc import AsyncIterator
from typing import cast

import pytest
from rakit_core.errors import ErrorCode, RakitError
from rakit_core.events import EventPublisher
from rakit_core.operations import (
    CancellationContext,
    Deadline,
    OperationContext,
    activate_operation_context,
    run_with_deadline,
)
from rakit_core.transactions import TransactionPolicy
from rakit_sqlalchemy.uow import SQLAlchemyUnitOfWork
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "uow_users"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str]


@pytest.fixture
async def session_factory() -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    yield async_sessionmaker(engine, expire_on_commit=False)
    await engine.dispose()


@pytest.mark.anyio
async def test_auto_policy_commits_only_after_success(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with SQLAlchemyUnitOfWork(session_factory, policy=TransactionPolicy.AUTO) as uow:
        uow.session.add(User(name="Ada"))
        await uow.mark_success()

    async with session_factory() as session:
        assert await session.scalar(select(func.count(User.id))) == 1


@pytest.mark.anyio
async def test_auto_policy_rolls_back_when_the_operation_raises(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    with pytest.raises(RuntimeError, match="boom"):
        async with SQLAlchemyUnitOfWork(session_factory, policy=TransactionPolicy.AUTO) as uow:
            uow.session.add(User(name="Ada"))
            raise RuntimeError("boom")

    async with session_factory() as session:
        assert await session.scalar(select(func.count(User.id))) == 0


@pytest.mark.anyio
async def test_cancellation_during_commit_waits_for_the_durable_outcome() -> None:
    """Once commit starts, cancellation cannot produce false rollback semantics."""
    entered = asyncio.Event()
    release = asyncio.Event()

    class Session:
        committed = False
        rolled_back = False

        async def commit(self) -> None:
            entered.set()
            await release.wait()
            self.committed = True

        async def rollback(self) -> None:
            self.rolled_back = True

        async def close(self) -> None:
            return None

    session = Session()

    async def operation() -> None:
        factory = cast(async_sessionmaker[AsyncSession], lambda: session)
        async with SQLAlchemyUnitOfWork(factory) as uow:
            await uow.mark_success()

    task = asyncio.create_task(operation())
    await entered.wait()
    task.cancel()
    release.set()
    await task

    assert session.committed is True
    assert session.rolled_back is False


@pytest.mark.anyio
async def test_cancellation_at_the_pre_commit_checkpoint_rolls_back() -> None:
    """The last cooperative checkpoint must abort before commit starts."""

    class Session:
        committed = False
        rolled_back = False

        async def commit(self) -> None:
            self.committed = True

        async def rollback(self) -> None:
            self.rolled_back = True

        async def close(self) -> None:
            return None

    session = Session()
    cancellation = CancellationContext()
    context = OperationContext(deadline=Deadline.after(30), cancellation=cancellation)
    factory = cast(async_sessionmaker[AsyncSession], lambda: session)

    with pytest.raises(RakitError) as caught:
        async with SQLAlchemyUnitOfWork(factory, operation_context=context) as uow:
            await uow.mark_success()
            cancellation.cancel()

    assert caught.value.code == ErrorCode.OPERATION_TIMEOUT
    assert session.committed is False
    assert session.rolled_back is True


@pytest.mark.anyio
async def test_commit_failure_rolls_back_without_delivering_after_commit() -> None:
    """A failed durable commit is not a successful mutation outcome."""

    class Session:
        rolled_back = False

        async def commit(self) -> None:
            raise RuntimeError("database unavailable")

        async def rollback(self) -> None:
            self.rolled_back = True

        async def close(self) -> None:
            return None

    class Publisher:
        after_commit_calls = 0
        after_rollback_calls = 0

        async def after_commit(self) -> None:
            self.after_commit_calls += 1

        def after_rollback(self) -> None:
            self.after_rollback_calls += 1

    session = Session()
    publisher = Publisher()
    factory = cast(async_sessionmaker[AsyncSession], lambda: session)

    with pytest.raises(RuntimeError, match="database unavailable"):
        async with SQLAlchemyUnitOfWork(
            factory, event_publisher=cast(EventPublisher, publisher)
        ) as uow:
            await uow.mark_success()

    assert session.rolled_back is True
    assert publisher.after_commit_calls == 0
    assert publisher.after_rollback_calls == 1


@pytest.mark.anyio
async def test_nested_uow_inherits_parent_session_and_outermost_owner_commits(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with SQLAlchemyUnitOfWork(session_factory) as outer:
        outer.session.add(User(name="outer"))
        async with SQLAlchemyUnitOfWork(session_factory) as nested:
            assert nested.session is outer.session
            nested.session.add(User(name="nested"))
            await nested.mark_success()
        # The child must not commit the parent transaction early.
        async with session_factory() as observer:
            assert await observer.scalar(select(func.count(User.id))) == 0
        await outer.mark_success()

    async with session_factory() as session:
        assert await session.scalar(select(func.count(User.id))) == 2


@pytest.mark.anyio
async def test_explicit_nested_savepoint_rolls_back_only_child_changes(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with SQLAlchemyUnitOfWork(session_factory) as outer:
        outer.session.add(User(name="outer"))
        with pytest.raises(RuntimeError, match="child failure"):
            async with SQLAlchemyUnitOfWork(session_factory, savepoint=True) as nested:
                nested.session.add(User(name="child"))
                raise RuntimeError("child failure")
        await outer.mark_success()

    async with session_factory() as session:
        assert list((await session.scalars(select(User.name))).all()) == ["outer"]


@pytest.mark.anyio
async def test_nested_failure_without_savepoint_poison_parent_transaction(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with SQLAlchemyUnitOfWork(session_factory) as outer:
        outer.session.add(User(name="outer"))
        with pytest.raises(RuntimeError, match="child failure"):
            async with SQLAlchemyUnitOfWork(session_factory) as nested:
                nested.session.add(User(name="child"))
                raise RuntimeError("child failure")
        await outer.mark_success()

    async with session_factory() as session:
        assert list((await session.scalars(select(User.name))).all()) == []


@pytest.mark.anyio
async def test_explicit_savepoint_is_rejected_when_active_session_lacks_capability() -> None:
    class Session:
        async def rollback(self) -> None:
            return None

        async def close(self) -> None:
            return None

    session = Session()
    factory = cast(async_sessionmaker[AsyncSession], lambda: session)

    async with SQLAlchemyUnitOfWork(factory):
        with pytest.raises(RuntimeError, match="does not support savepoints"):
            async with SQLAlchemyUnitOfWork(factory, savepoint=True):
                pass


@pytest.mark.anyio
async def test_anyio_timeout_waits_for_a_commit_that_has_already_begun() -> None:
    entered = asyncio.Event()

    class Session:
        committed = False
        rolled_back = False

        async def commit(self) -> None:
            entered.set()
            await asyncio.sleep(0.02)
            self.committed = True

        async def rollback(self) -> None:
            self.rolled_back = True

        async def close(self) -> None:
            return None

    session = Session()
    factory = cast(async_sessionmaker[AsyncSession], lambda: session)

    async def operation() -> None:
        async with SQLAlchemyUnitOfWork(factory) as uow:
            await uow.mark_success()

    deadline = Deadline.after(0.001)
    context = OperationContext(deadline=deadline, cancellation=CancellationContext())
    with activate_operation_context(context):
        await run_with_deadline(operation(), deadline)

    assert entered.is_set()
    assert session.committed is True
    assert session.rolled_back is False
