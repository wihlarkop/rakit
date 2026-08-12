import asyncio
from collections.abc import AsyncIterator
from typing import cast

import pytest
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
