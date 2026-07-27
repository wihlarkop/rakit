from datetime import UTC, datetime

from rakit_core.auth import SessionRecord
from rakit_core.crypto import TokenService


class CsrfService:
    """Issues and verifies CSRF tokens bound to a session.

    A CSRF token is not stored session state: it is a `TokenService`-derived
    value (purpose `"csrf"`) that can be freshly issued whenever needed and
    verified without any database lookup, deliberately separate from
    `SessionRecord` (see `rakit_core.auth`).

    There is no default TTL, by design. A token is issued once, at login,
    and no code path re-issues it, so its lifetime has to match the session
    it protects: too short and every later state-changing request (logout
    included) fails 403 permanently, with no recovery short of clearing
    cookies; too long and it outlives what it is bound to. No constant can
    satisfy that for every deployment -- the previous 14-day default was
    `SQLAlchemySessionStore`'s own default copied into a different package,
    so any deployment configuring a different absolute session lifetime
    silently got the wrong answer. The expiry is read from the actual
    `SessionRecord` instead.

    A longer-lived token grants no extra power regardless: verification is
    always scoped to a `session_id` whose session the caller has already
    resolved as live, so the session's own idle/absolute expiry remains the
    real bound.
    """

    def __init__(self, token_service: TokenService) -> None:
        self._token_service = token_service

    def issue(self, session: SessionRecord, *, expires_at: datetime | None = None) -> str:
        """Issue a token bound to `session`, expiring when the session does.

        `expires_at` lets a deployment choose a *shorter* window than the
        session's own deadline -- an explicit choice, never an inherited
        default. An already-expired session raises rather than minting a
        token that could never be used: `TokenService.issue_in` rejects a
        non-positive TTL, which is the correct fail-closed answer here.
        """
        deadline = expires_at if expires_at is not None else session.absolute_expires_at
        ttl = deadline - datetime.now(UTC)
        return self._token_service.issue_in("csrf", {"session_id": session.session_id}, ttl)

    def verify(self, token: str, *, session_id: str) -> bool:
        try:
            claims = self._token_service.verify(token, expected_purpose="csrf")
        except ValueError:
            return False
        return claims.get("session_id") == session_id
