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
    claimed: bool = True


class IdempotencyStore(Protocol):
    async def begin(self, token_hash: str, *, fingerprint: str) -> IdempotencyReservation: ...

    async def complete(
        self, reservation: IdempotencyReservation, receipt: OperationReceipt
    ) -> None: ...

    async def release(self, reservation: IdempotencyReservation) -> None:
        """Release a pre-commit claim so a failed operation may be retried."""
        ...

    async def fail_final(self, reservation: IdempotencyReservation) -> None:
        """Record a non-retryable operation failure without exposing request data."""
        ...
