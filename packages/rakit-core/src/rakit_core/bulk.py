"""Safe-by-default bulk policy metadata; execution is intentionally deferred."""

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class BulkExecutionPolicy(StrEnum):
    ATOMIC = "atomic"
    BEST_EFFORT = "best_effort"


class BulkPolicy(BaseModel):
    model_config = ConfigDict(frozen=True)

    execution: BulkExecutionPolicy = BulkExecutionPolicy.ATOMIC
    confirmation_threshold: int = Field(default=25, ge=0)
    synchronous_maximum: int = Field(default=1000, ge=1)
    require_concurrency_snapshot: bool = True
