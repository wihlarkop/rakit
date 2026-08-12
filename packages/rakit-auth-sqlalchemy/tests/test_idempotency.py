import asyncio
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from rakit_auth_sqlalchemy.idempotency import SQLAlchemyIdempotencyStore
from rakit_auth_sqlalchemy.models import Base
from rakit_core.errors import ErrorCode, RakitError
from rakit_core.idempotency import OperationReceipt
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine


@pytest.fixture
async def session_factory() -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    yield async_sessionmaker(engine, expire_on_commit=False)
    await engine.dispose()


@pytest.mark.anyio
async def test_completed_submission_replays_its_safe_receipt(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    store = SQLAlchemyIdempotencyStore(session_factory)
    reservation = await store.begin("token-hash", fingerprint="abc")
    receipt = OperationReceipt(
        operation_id="op-1",
        status="succeeded",
        result_kind="redirect",
        redirect_route="rakit.operations.resources.users.detail",
    )

    await store.complete(reservation, receipt)
    replay = await store.begin("token-hash", fingerprint="abc")

    assert replay.completed_receipt == receipt


@pytest.mark.anyio
async def test_same_token_with_a_different_payload_is_rejected(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    store = SQLAlchemyIdempotencyStore(session_factory)
    await store.begin("token-hash", fingerprint="abc")

    with pytest.raises(RakitError) as caught:
        await store.begin("token-hash", fingerprint="def")
    assert caught.value.code == ErrorCode.VALIDATION_FAILED


@pytest.mark.anyio
async def test_concurrent_claims_have_one_authoritative_reservation(tmp_path: Path) -> None:
    """A database unique constraint, not a worker-local lock, picks the winner."""
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'idempotency.db'}")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    store = SQLAlchemyIdempotencyStore(factory)

    first, second = await asyncio.gather(
        store.begin("same-token", fingerprint="same-request"),
        store.begin("same-token", fingerprint="same-request"),
    )

    assert {first.status, second.status} == {first.status}
    assert first.reservation_id == second.reservation_id
    await engine.dispose()


@pytest.mark.anyio
async def test_failed_reservation_is_released_for_a_retry(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    store = SQLAlchemyIdempotencyStore(session_factory)
    reservation = await store.begin("retry-token", fingerprint="request")
    await store.release(reservation)

    retry = await store.begin("retry-token", fingerprint="request")
    assert retry.status.value == "in_progress"
    assert retry.completed_receipt is None
