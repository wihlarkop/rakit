import asyncio
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from rakit_auth_sqlalchemy.idempotency import SQLAlchemyIdempotencyStore
from rakit_auth_sqlalchemy.models import Base, IdempotencyRecord
from rakit_core.errors import ErrorCode, RakitError
from rakit_core.idempotency import IdempotencyStatus, OperationReceipt
from sqlalchemy import update
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

    assert sum(reservation.claimed for reservation in (first, second)) == 1
    assert {first.status, second.status} == {IdempotencyStatus.IN_PROGRESS}
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


@pytest.mark.anyio
async def test_stale_in_progress_claim_is_expired_then_reclaimed(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    store = SQLAlchemyIdempotencyStore(session_factory)
    first = await store.begin("stale-token", fingerprint="request")
    async with session_factory() as session:
        await session.execute(
            update(IdempotencyRecord)
            .where(IdempotencyRecord.id == first.reservation_id)
            .values(expires_at=datetime.now(UTC) - timedelta(seconds=1))
        )
        await session.commit()

    reclaimed = await store.begin("stale-token", fingerprint="request")

    assert reclaimed.claimed is True
    assert reclaimed.status is IdempotencyStatus.IN_PROGRESS
    assert reclaimed.reservation_id == first.reservation_id


@pytest.mark.anyio
async def test_final_failure_is_not_reclaimed(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    store = SQLAlchemyIdempotencyStore(session_factory)
    first = await store.begin("final-token", fingerprint="request")
    await store.fail_final(first)

    retry = await store.begin("final-token", fingerprint="request")

    assert retry.claimed is False
    assert retry.status is IdempotencyStatus.FAILED_FINAL


@pytest.mark.anyio
async def test_reclaimed_reservation_cannot_be_completed_by_previous_owner(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """A worker that lost its lease cannot overwrite the new owner's state."""
    store = SQLAlchemyIdempotencyStore(session_factory)
    first = await store.begin("lease-owner", fingerprint="request")
    await store.release(first)
    reclaimed = await store.begin("lease-owner", fingerprint="request")

    with pytest.raises(RakitError) as caught:
        await store.complete(
            first,
            OperationReceipt(operation_id="old", status="succeeded", result_kind="redirect"),
        )

    assert caught.value.code == ErrorCode.RESOURCE_CONFLICT
    retry = await store.begin("lease-owner", fingerprint="request")
    assert retry.claimed is False
    assert retry.status is IdempotencyStatus.IN_PROGRESS
    assert retry.reservation_id == reclaimed.reservation_id


@pytest.mark.anyio
async def test_concurrent_retryable_reclaims_have_one_owner(tmp_path: Path) -> None:
    """Separate sessions must use the conditional transition as arbitration."""
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'retryable.db'}")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    store = SQLAlchemyIdempotencyStore(factory)
    first = await store.begin("retryable-token", fingerprint="request")
    await store.release(first)

    left, right = await asyncio.gather(
        store.begin("retryable-token", fingerprint="request"),
        store.begin("retryable-token", fingerprint="request"),
    )

    assert sum(reservation.claimed for reservation in (left, right)) == 1
    assert {left.status, right.status} == {IdempotencyStatus.IN_PROGRESS}
    await engine.dispose()


@pytest.mark.anyio
async def test_concurrent_expired_lease_reclaims_have_one_owner(tmp_path: Path) -> None:
    """An expired worker lease is reclaimed exactly once across connections."""
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'expired.db'}")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    store = SQLAlchemyIdempotencyStore(factory)
    first = await store.begin("expired-token", fingerprint="request")
    async with factory() as session:
        await session.execute(
            update(IdempotencyRecord)
            .where(IdempotencyRecord.id == first.reservation_id)
            .values(expires_at=datetime.now(UTC) - timedelta(seconds=1))
        )
        await session.commit()

    left, right = await asyncio.gather(
        store.begin("expired-token", fingerprint="request"),
        store.begin("expired-token", fingerprint="request"),
    )

    assert sum(reservation.claimed for reservation in (left, right)) == 1
    assert {left.status, right.status} == {IdempotencyStatus.IN_PROGRESS}
    await engine.dispose()


@pytest.mark.anyio
async def test_completed_replay_is_terminal_under_concurrent_attempts(tmp_path: Path) -> None:
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'completed.db'}")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    store = SQLAlchemyIdempotencyStore(factory)
    owner = await store.begin("completed-token", fingerprint="request")
    receipt = OperationReceipt(operation_id="op-1", status="succeeded", result_kind="redirect")
    await store.complete(owner, receipt)

    left, right = await asyncio.gather(
        store.begin("completed-token", fingerprint="request"),
        store.begin("completed-token", fingerprint="request"),
    )

    assert not left.claimed and not right.claimed
    assert left.completed_receipt == receipt
    assert right.completed_receipt == receipt
    await engine.dispose()


@pytest.mark.anyio
async def test_different_fingerprint_is_rejected_under_initial_claim_contention(
    tmp_path: Path,
) -> None:
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'mismatch.db'}")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    store = SQLAlchemyIdempotencyStore(factory)

    results = await asyncio.gather(
        store.begin("same-token", fingerprint="first"),
        store.begin("same-token", fingerprint="second"),
        return_exceptions=True,
    )

    assert sum(isinstance(result, RakitError) for result in results) == 1
    assert sum(not isinstance(result, Exception) for result in results) == 1
    assert (
        next(result for result in results if isinstance(result, RakitError)).code
        == ErrorCode.VALIDATION_FAILED
    )
    await engine.dispose()
