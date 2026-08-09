"""Database-backed duplicate-submission protection."""

from rakit_core.errors import ErrorCode, RakitError
from rakit_core.idempotency import (
    IdempotencyReservation,
    IdempotencyStatus,
    OperationReceipt,
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from .models import IdempotencyRecord


class SQLAlchemyIdempotencyStore:
    production_safe = True

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def begin(self, token_hash: str, *, fingerprint: str) -> IdempotencyReservation:
        async with self._session_factory() as session:
            row = await self._find(session, token_hash)
            if row is None:
                row = IdempotencyRecord(
                    token_hash=token_hash,
                    fingerprint=fingerprint,
                    status=IdempotencyStatus.IN_PROGRESS,
                )
                session.add(row)
                await session.commit()
                await session.refresh(row)
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
