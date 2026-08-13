"""Safe-by-default bulk policy metadata; execution is intentionally deferred."""

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class BulkExecutionPolicy(StrEnum):
    ATOMIC = "atomic"
    BEST_EFFORT = "best_effort"


BULK_CONFIRMATION_THRESHOLD_MAXIMUM = 25
SYNCHRONOUS_BULK_TARGETS_MAXIMUM = 1000


class BulkPolicy(BaseModel):
    model_config = ConfigDict(frozen=True)

    execution: BulkExecutionPolicy = BulkExecutionPolicy.ATOMIC
    confirmation_threshold: int = Field(default=BULK_CONFIRMATION_THRESHOLD_MAXIMUM, ge=0, le=25)
    synchronous_maximum: int = Field(default=SYNCHRONOUS_BULK_TARGETS_MAXIMUM, ge=1, le=1000)
    require_concurrency_snapshot: bool = True
