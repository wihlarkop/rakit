from datetime import timedelta

from rakit_core.crypto import TokenService

_CSRF_TTL = timedelta(hours=4)


class CsrfService:
    """Issues and verifies CSRF tokens bound to a `session_id`.

    A CSRF token is not stored session state: it is a `TokenService`-derived
    value (purpose `"csrf"`) that can be freshly issued whenever needed and
    verified without any database lookup, deliberately separate from
    `SessionRecord` (see `rakit_core.auth`).
    """

    def __init__(self, token_service: TokenService) -> None:
        self._token_service = token_service

    def issue(self, session_id: str) -> str:
        return self._token_service.issue_in("csrf", {"session_id": session_id}, _CSRF_TTL)

    def verify(self, token: str, *, session_id: str) -> bool:
        try:
            claims = self._token_service.verify(token, expected_purpose="csrf")
        except ValueError:
            return False
        return claims.get("session_id") == session_id
