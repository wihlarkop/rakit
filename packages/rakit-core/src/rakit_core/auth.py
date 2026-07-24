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

    async def resolve_principal(self, subject_id: str) -> Principal | None:
        """Re-resolve a `Principal` from a durable `subject_id` (a resolved
        `SessionRecord.subject_id`), independent of any password.

        Called on every authenticated request -- not just at login -- so a
        request always reflects the subject's *current* active/permission
        state rather than whatever was true when the session was created.
        Returns `None` if the subject no longer exists or is no longer
        active; a caller resolving a request's `Principal` this way must
        treat that as "unauthenticated," not merely "no permissions."
        """
        ...


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
        """Issue a genuinely new session (new `session_id`, new raw token)
        for the same principal, preserving the original absolute-expiry
        boundary, and revoke the previous `session_id`. Used on privilege
        change.

        The returned record's `session_id` MUST differ from the one passed
        in -- a CSRF token is bound to `session_id`, not to the raw token
        (see `rakit_web`'s `CsrfService`), so reusing the same `session_id`
        would leave any CSRF token issued before rotation valid forever
        after it. Callers must reissue a CSRF token bound to the *new*
        `session_id` after calling this.
        """
        ...

    async def revoke(self, session_id: str) -> None:
        """Revoke a session so it no longer resolves."""
        ...
