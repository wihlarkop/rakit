from datetime import datetime
from typing import Protocol

from pydantic import BaseModel, ConfigDict


class Principal(BaseModel):
    """The authenticated (or anonymous) identity attached to a request.

    Immutable and backend-neutral: it carries only the facts request
    handling and authorization need (subject, authentication state, display
    name, resolved permission keys, superuser flag) -- never credentials or
    a reference to the underlying storage row.
    """

    model_config = ConfigDict(frozen=True)

    subject_id: str | None = None
    authenticated: bool = False
    display_name: str | None = None
    permissions: frozenset[str] = frozenset()
    is_superuser: bool = False


ANONYMOUS_PRINCIPAL = Principal()


class SessionRecord(BaseModel):
    """An opaque, resolved server-side session -- never the raw browser
    token, which only ever exists as a `SessionStore.create`/`.rotate`
    return value and a cookie value, never persisted or logged.

    Deliberately carries no CSRF token: a CSRF token is not session state,
    it is a `TokenService`-derived value bound to `session_id` (see
    `rakit_core.crypto.TokenService` and `rakit_web`'s `CsrfService`), so it
    never needs to be stored, rotated in the database, or read back out of
    a session row.
    """

    model_config = ConfigDict(frozen=True)

    session_id: str
    subject_id: str
    created_at: datetime
    last_seen_at: datetime
    idle_expires_at: datetime
    absolute_expires_at: datetime


class AuthBackend(Protocol):
    """Verifies a login identifier/password pair and resolves the
    authenticated `Principal`, or returns `None` for any failure reason
    (unknown identifier, wrong password, inactive account) -- callers must
    not be able to distinguish these cases from the return value alone,
    since doing so would let a login endpoint enumerate valid identifiers.
    """

    async def authenticate(self, identifier: str, password: str) -> Principal | None: ...


class SessionStore(Protocol):
    """Server-side opaque session storage. Implementations persist only a
    hash of the raw browser token, never the token itself."""

    async def create(self, principal: Principal) -> tuple[str, SessionRecord]:
        """Create a new session for `principal`, returning `(raw_token, record)`."""
        ...

    async def resolve(self, raw_token: str) -> SessionRecord | None:
        """Resolve a raw browser token to its session record, or `None` if
        the token is unknown, revoked, or past idle/absolute expiry."""
        ...

    async def rotate(self, session_id: str) -> tuple[str, SessionRecord]:
        """Issue a new raw token for an existing session, invalidating the
        previous raw token. Used on privilege change; callers must also
        reissue a CSRF token bound to the (unchanged) `session_id`."""
        ...

    async def revoke(self, session_id: str) -> None:
        """Revoke a session so it no longer resolves."""
        ...
