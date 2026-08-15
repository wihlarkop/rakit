"""Safe-by-default bulk action policy and execution contracts."""

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from ._immutability import freeze_mapping
from .identity import RecordIdentity


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


@dataclass(frozen=True)
class BulkTarget:
    """One server-resolved target in a bulk action selection."""

    identity: RecordIdentity
    record: object


@dataclass(frozen=True)
class BulkSelection:
    """Ordered, duplicate-free selection resolved through the scoped resource service."""

    targets: tuple[BulkTarget, ...]

    def __post_init__(self) -> None:
        if not self.targets:
            raise ValueError("Bulk selection requires at least one target")
        identities = tuple(target.identity for target in self.targets)
        if len(set(str(dict(identity.values)) for identity in identities)) != len(identities):
            raise ValueError("Bulk selection identities must be unique")

    @property
    def identities(self) -> tuple[RecordIdentity, ...]:
        return tuple(target.identity for target in self.targets)


class BulkItemStatus(StrEnum):
    SUCCEEDED = "succeeded"
    REJECTED = "rejected"
    SKIPPED = "skipped"


@dataclass(frozen=True)
class BulkItemOutcome:
    """Safe semantic outcome for one selected target; arbitrary action payloads are excluded."""

    identity: RecordIdentity
    status: BulkItemStatus
    message: str | None = None
    errors: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "errors", freeze_mapping(dict(self.errors)))


@dataclass(frozen=True)
class BulkActionOutcome:
    """Aggregate semantic result for one synchronous bulk execution."""

    execution: BulkExecutionPolicy
    items: tuple[BulkItemOutcome, ...]

    @property
    def selected_count(self) -> int:
        return len(self.items)

    @property
    def succeeded_count(self) -> int:
        return sum(item.status is BulkItemStatus.SUCCEEDED for item in self.items)

    @property
    def rejected_count(self) -> int:
        return sum(item.status is BulkItemStatus.REJECTED for item in self.items)

    @property
    def skipped_count(self) -> int:
        return sum(item.status is BulkItemStatus.SKIPPED for item in self.items)

    @property
    def all_succeeded(self) -> bool:
        return bool(self.items) and self.succeeded_count == self.selected_count
