"""Backend-neutral duplicate-submission state contracts."""

from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol


class IdempotencyStatus(StrEnum):
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED_RETRYABLE = "failed_retryable"
    FAILED_FINAL = "failed_final"
    EXPIRED = "expired"


@dataclass(frozen=True)
class OperationReceipt:
    operation_id: str
    status: str
    result_kind: str
    redirect_route: str | None = None


@dataclass(frozen=True)
class IdempotencyReservation:
    reservation_id: int
    status: IdempotencyStatus
    completed_receipt: OperationReceipt | None = None


class IdempotencyStore(Protocol):
    async def begin(self, token_hash: str, *, fingerprint: str) -> IdempotencyReservation: ...

    async def complete(
        self, reservation: IdempotencyReservation, receipt: OperationReceipt
    ) -> None: ...
