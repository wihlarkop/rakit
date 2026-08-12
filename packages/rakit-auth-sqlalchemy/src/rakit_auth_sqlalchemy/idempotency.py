"""Database-backed duplicate-submission protection."""

from datetime import UTC, datetime, timedelta

from rakit_core.errors import ErrorCode, RakitError
from rakit_core.idempotency import (
    IdempotencyReservation,
    IdempotencyStatus,
    OperationReceipt,
)
from sqlalchemy import select, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, AsyncSession, async_sessionmaker

from .models import IdempotencyRecord


class SQLAlchemyIdempotencyStore:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        *,
        lease: timedelta = timedelta(minutes=15),
    ) -> None:
        if lease <= timedelta(0):
            raise ValueError("idempotency lease must be positive")
        self._session_factory = session_factory
        self._lease = lease

    @property
    def production_safe(self) -> bool:
        """Derive deployment safety from the *current* session-factory bind."""
        bind = self._session_factory.kw.get("bind")
        dialect = getattr(bind, "dialect", None)
        dialect_name = getattr(dialect, "name", None)
        return (
            isinstance(bind, AsyncEngine | AsyncConnection)
            and isinstance(dialect_name, str)
            and dialect_name != "sqlite"
        )

    async def begin(self, token_hash: str, *, fingerprint: str) -> IdempotencyReservation:
        async with self._session_factory() as session:
            row = await self._find(session, token_hash)
            claimed = False
            now = datetime.now(UTC)
            if row is None:
                row = IdempotencyRecord(
                    token_hash=token_hash,
                    fingerprint=fingerprint,
                    status=IdempotencyStatus.IN_PROGRESS,
                    expires_at=now + self._lease,
                    claim_generation=1,
                )
                session.add(row)
                try:
                    await session.commit()
                    await session.refresh(row)
                    claimed = True
                except IntegrityError:
                    # Another transaction won the unique-token race.  Roll
                    # back the failed insert before reading its authoritative
                    # claim; this remains correct across workers/processes.
                    await session.rollback()
                    row = await self._find(session, token_hash)
                    if row is None:
                        raise RakitError(
                            code=ErrorCode.INTERNAL_ERROR,
                            message="Could not establish submission claim.",
                            status_code=500,
                        ) from None
            if row.fingerprint != fingerprint:
                raise RakitError(
                    code=ErrorCode.VALIDATION_FAILED,
                    message="Submission token does not match this request.",
                    status_code=400,
                )
            status = IdempotencyStatus(row.status)
            if status is IdempotencyStatus.IN_PROGRESS:
                # A dead worker leaves a leased claim behind.  First record
                # its expiration with a state-predicated transition, then let
                # exactly one caller reclaim that durable EXPIRED state.
                expired = await session.execute(
                    update(IdempotencyRecord)
                    .where(
                        IdempotencyRecord.id == row.id,
                        IdempotencyRecord.status == IdempotencyStatus.IN_PROGRESS,
                        IdempotencyRecord.expires_at <= now,
                    )
                    .values(status=IdempotencyStatus.EXPIRED),
                    execution_options={"synchronize_session": False},
                )
                await session.commit()
                if isinstance(expired, CursorResult) and expired.rowcount == 1:
                    await session.refresh(row)
                    status = IdempotencyStatus(row.status)
                else:
                    # A concurrent worker may already have materialized the
                    # lease expiry or reclaimed it.  Never return the stale
                    # ORM snapshot as authoritative state.
                    session.expire_all()
                    row = await self._find(session, token_hash)
                    assert row is not None
                    status = IdempotencyStatus(row.status)

            reclaim_statement = None
            if status in {IdempotencyStatus.FAILED_RETRYABLE, IdempotencyStatus.EXPIRED}:
                reclaim_statement = update(IdempotencyRecord).where(
                    IdempotencyRecord.id == row.id,
                    IdempotencyRecord.status == status,
                )
            if reclaim_statement is not None:
                transitioned = await session.execute(
                    reclaim_statement.values(
                        status=IdempotencyStatus.IN_PROGRESS,
                        expires_at=now + self._lease,
                        receipt=None,
                        claim_generation=IdempotencyRecord.claim_generation + 1,
                    ),
                    execution_options={"synchronize_session": False},
                )
                await session.commit()
                claimed = isinstance(transitioned, CursorResult) and transitioned.rowcount == 1
                if claimed:
                    await session.refresh(row)
                    status = IdempotencyStatus(row.status)
                else:
                    session.expire_all()
                    row = await self._find(session, token_hash)
                    assert row is not None
                    status = IdempotencyStatus(row.status)
            receipt = self._receipt(row.receipt) if status is IdempotencyStatus.COMPLETED else None
            return IdempotencyReservation(
                reservation_id=row.id,
                status=status,
                completed_receipt=receipt,
                claimed=claimed,
                claim_generation=row.claim_generation,
            )

    async def complete(
        self, reservation: IdempotencyReservation, receipt: OperationReceipt
    ) -> None:
        async with self._session_factory() as session:
            transitioned = await session.execute(
                update(IdempotencyRecord)
                .where(
                    IdempotencyRecord.id == reservation.reservation_id,
                    IdempotencyRecord.status == IdempotencyStatus.IN_PROGRESS,
                    IdempotencyRecord.claim_generation == reservation.claim_generation,
                )
                .values(
                    status=IdempotencyStatus.COMPLETED,
                    receipt={
                        "operation_id": receipt.operation_id,
                        "status": receipt.status,
                        "result_kind": receipt.result_kind,
                        "redirect_route": receipt.redirect_route,
                    },
                    expires_at=None,
                ),
                execution_options={"synchronize_session": False},
            )
            await session.commit()
            if not isinstance(transitioned, CursorResult) or transitioned.rowcount != 1:
                raise RakitError(
                    code=ErrorCode.RESOURCE_CONFLICT,
                    message="Submission reservation is no longer active.",
                    status_code=409,
                )

    async def release(self, reservation: IdempotencyReservation) -> None:
        """Record a retryable pre-commit failure without losing audit state."""
        async with self._session_factory() as session:
            await session.execute(
                update(IdempotencyRecord)
                .where(
                    IdempotencyRecord.id == reservation.reservation_id,
                    IdempotencyRecord.status == IdempotencyStatus.IN_PROGRESS,
                    IdempotencyRecord.claim_generation == reservation.claim_generation,
                )
                .values(status=IdempotencyStatus.FAILED_RETRYABLE, expires_at=datetime.now(UTC))
            )
            await session.commit()

    async def fail_final(self, reservation: IdempotencyReservation) -> None:
        """Make a non-retryable rejection terminal without storing request data."""
        async with self._session_factory() as session:
            await session.execute(
                update(IdempotencyRecord)
                .where(
                    IdempotencyRecord.id == reservation.reservation_id,
                    IdempotencyRecord.status == IdempotencyStatus.IN_PROGRESS,
                    IdempotencyRecord.claim_generation == reservation.claim_generation,
                )
                .values(status=IdempotencyStatus.FAILED_FINAL)
            )
            await session.commit()

    @staticmethod
    async def _find(session: AsyncSession, token_hash: str) -> IdempotencyRecord | None:
        return (
            await session.scalars(
                select(IdempotencyRecord).where(IdempotencyRecord.token_hash == token_hash)
            )
        ).one_or_none()

    @staticmethod
    def _receipt(value: dict[str, str | None] | None) -> OperationReceipt | None:
        if value is None:
            return None
        operation_id = value.get("operation_id")
        status = value.get("status")
        result_kind = value.get("result_kind")
        redirect_route = value.get("redirect_route")
        if (
            not isinstance(operation_id, str)
            or not isinstance(status, str)
            or not isinstance(result_kind, str)
        ):
            return None
        return OperationReceipt(
            operation_id=operation_id,
            status=status,
            result_kind=result_kind,
            redirect_route=redirect_route if isinstance(redirect_route, str) else None,
        )
