"""Closed, user-safe authentication presentation state."""

from enum import StrEnum


class AuthReason(StrEnum):
    """Reasons that may safely cross the browser redirect boundary."""

    SESSION_EXPIRED = "session_expired"
    SIGNED_OUT = "signed_out"


__all__ = ["AuthReason"]
