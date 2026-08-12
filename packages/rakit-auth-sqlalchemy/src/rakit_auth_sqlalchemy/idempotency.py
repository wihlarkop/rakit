"""Database-backed duplicate-submission protection."""

from rakit_core.errors import ErrorCode, RakitError
from rakit_core.idempotency import (
    IdempotencyReservation,
    IdempotencyStatus,
    OperationReceipt,
)
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, AsyncSession, async_sessionmaker

from .models import IdempotencyRecord


class SQLAlchemyIdempotencyStore:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

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
            if row is None:
                row = IdempotencyRecord(
                    token_hash=token_hash,
                    fingerprint=fingerprint,
                    status=IdempotencyStatus.IN_PROGRESS,
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
            receipt = self._receipt(row.receipt) if status is IdempotencyStatus.COMPLETED else None
            return IdempotencyReservation(
                reservation_id=row.id,
                status=status,
                completed_receipt=receipt,
                claimed=claimed,
            )

    async def complete(
        self, reservation: IdempotencyReservation, receipt: OperationReceipt
    ) -> None:
        async with self._session_factory() as session:
            row = await session.get(IdempotencyRecord, reservation.reservation_id)
            if row is None:
                raise RakitError(
                    code=ErrorCode.VALIDATION_FAILED,
                    message="Unknown submission reservation.",
                    status_code=400,
                )
            row.status = IdempotencyStatus.COMPLETED
            row.receipt = {
                "operation_id": receipt.operation_id,
                "status": receipt.status,
                "result_kind": receipt.result_kind,
                "redirect_route": receipt.redirect_route,
            }
            await session.commit()

    async def release(self, reservation: IdempotencyReservation) -> None:
        """Drop only a still-in-progress claim after pre-commit failure."""
        async with self._session_factory() as session:
            await session.execute(
                delete(IdempotencyRecord).where(
                    IdempotencyRecord.id == reservation.reservation_id,
                    IdempotencyRecord.status == IdempotencyStatus.IN_PROGRESS,
                )
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
