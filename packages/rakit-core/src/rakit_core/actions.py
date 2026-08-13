"""Foundation contracts for later unified action execution."""

from dataclasses import dataclass
from enum import StrEnum


class ActionScope(StrEnum):
    PAGE = "page"
    RESOURCE = "resource"
    RECORD = "record"
    BULK = "bulk"


class ActionAvailability(StrEnum):
    AVAILABLE = "available"
    DISABLED = "disabled"
    HIDDEN = "hidden"


@dataclass(frozen=True)
class ActionResult[TActionPayload]:
    """Backend-neutral semantic action outcome; web translation is later work."""

    payload: TActionPayload | None = None
    message: str | None = None
    target: str | None = None
