"""Backend-neutral semantic action outcomes for later web translation."""

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Any


class ActionScope(StrEnum):
    PAGE = "page"
    RESOURCE = "resource"
    RECORD = "record"
    BULK = "bulk"


class ActionAvailability(StrEnum):
    AVAILABLE = "available"
    DISABLED = "disabled"
    HIDDEN = "hidden"


class ActionResponseKind(StrEnum):
    """Explicit non-JSON response categories; adapters own concrete responses."""

    FILE = "file"
    STREAM = "stream"
    ADVANCED = "advanced"


@dataclass(frozen=True)
class ActionSuccess[TActionPayload]:
    payload: TActionPayload | None = None
    message: str | None = None


@dataclass(frozen=True)
class ActionRejected:
    """An expected validation or business-policy rejection, not an exception."""

    errors: Mapping[str, str]
    message: str | None = None

    def __post_init__(self) -> None:
        if not self.errors and self.message is None:
            raise ValueError("A rejected action result requires errors or a message")


@dataclass(frozen=True)
class ActionRedirect:
    location: str
    message: str | None = None

    def __post_init__(self) -> None:
        if not self.location.startswith("/"):
            raise ValueError("Action redirect locations must be absolute application paths")


@dataclass(frozen=True)
class ActionRefresh:
    target: str
    message: str | None = None

    def __post_init__(self) -> None:
        if not self.target:
            raise ValueError("Action refresh target must not be empty")


@dataclass(frozen=True)
class ActionRendered[TActionPayload]:
    """A named semantic fragment; core intentionally has no template engine."""

    fragment: str
    payload: TActionPayload | None = None
    message: str | None = None

    def __post_init__(self) -> None:
        if not self.fragment:
            raise ValueError("Action rendered fragment must not be empty")


@dataclass(frozen=True)
class ActionAdvancedResponse:
    """An explicit opt-in escape hatch, never a framework response object."""

    kind: ActionResponseKind
    payload: Any


type ActionResult[TActionPayload] = (
    ActionSuccess[TActionPayload]
    | ActionRejected
    | ActionRedirect
    | ActionRefresh
    | ActionRendered[TActionPayload]
    | ActionAdvancedResponse
)
