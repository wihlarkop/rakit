from datetime import timedelta

from rakit_core.crypto import TokenService

# Must not be shorter than the session lifetime it protects. A CSRF token
# is issued once, at login, and no code path re-issues it -- so a token
# that lapses while its session is still valid makes every subsequent
# state-changing request (logout included) fail 403 permanently, with no
# way to recover short of clearing cookies. 14 days matches
# `SQLAlchemySessionStore`'s default absolute session timeout.
#
# A longer-lived token grants no extra power: verification is always
# scoped to a `session_id` whose session the caller has already resolved as
# live, so the session's own idle/absolute expiry remains the real bound.
DEFAULT_CSRF_TTL = timedelta(days=14)


class CsrfService:
    """Issues and verifies CSRF tokens bound to a `session_id`.

    A CSRF token is not stored session state: it is a `TokenService`-derived
    value (purpose `"csrf"`) that can be freshly issued whenever needed and
    verified without any database lookup, deliberately separate from
    `SessionRecord` (see `rakit_core.auth`).

    `ttl` should be at least as long as the configured session absolute
    timeout -- see `DEFAULT_CSRF_TTL`.
    """

    def __init__(self, token_service: TokenService, *, ttl: timedelta = DEFAULT_CSRF_TTL) -> None:
        self._token_service = token_service
        self._ttl = ttl

    def issue(self, session_id: str) -> str:
        return self._token_service.issue_in("csrf", {"session_id": session_id}, self._ttl)

    def verify(self, token: str, *, session_id: str) -> bool:
        try:
            claims = self._token_service.verify(token, expected_purpose="csrf")
        except ValueError:
            return False
        return claims.get("session_id") == session_id
