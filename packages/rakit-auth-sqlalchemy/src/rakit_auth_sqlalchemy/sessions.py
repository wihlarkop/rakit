import hashlib
import secrets
from datetime import UTC, datetime, timedelta
from typing import Any, cast

from rakit_core.auth import Principal, SessionRecord
from rakit_core.crypto import MAX_TOKEN_TTL
from rakit_core.errors import ErrorCode, RakitError
from sqlalchemy import select, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from .models import Session as SessionRow

_DEFAULT_IDLE_TIMEOUT = timedelta(hours=2)
_DEFAULT_ABSOLUTE_TIMEOUT = timedelta(days=14)


def _invalid_session_config(reason: str) -> RakitError:
    return RakitError(
        code=ErrorCode.CONFIG_INVALID,
        message=f"Invalid session lifetime configuration: {reason}",
        status_code=500,
        details={"reason": reason},
    )


def _validate_session_lifetimes(idle_timeout: object, absolute_timeout: object) -> None:
    if not isinstance(idle_timeout, timedelta) or idle_timeout <= timedelta(0):
        raise _invalid_session_config("invalid_idle_timeout")
    if not isinstance(absolute_timeout, timedelta) or absolute_timeout <= timedelta(0):
        raise _invalid_session_config("invalid_absolute_timeout")
    if idle_timeout > absolute_timeout:
        raise _invalid_session_config("idle_timeout_exceeds_absolute")
    if absolute_timeout > MAX_TOKEN_TTL:
        raise _invalid_session_config("absolute_timeout_exceeds_token_limit")


def _hash_token(raw_token: str) -> str:
    return hashlib.sha256(raw_token.encode()).hexdigest()


def _as_aware(value: datetime) -> datetime:
    """SQLite round-trips `DateTime(timezone=True)` values as naive (it has
    no native timezone-aware type) -- treat a naive value read back from the
    database as UTC rather than comparing offset-aware to offset-naive."""
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def _to_record(row: SessionRow) -> SessionRecord:
    return SessionRecord(
        session_id=str(row.id),
        subject_id=str(row.user_id),
        created_at=_as_aware(row.created_at),
        last_seen_at=_as_aware(row.last_seen_at),
        idle_expires_at=_as_aware(row.idle_expires_at),
        absolute_expires_at=_as_aware(row.absolute_expires_at),
    )


def _parse_session_id(session_id: str) -> int | None:
    try:
        return int(session_id)
    except ValueError:
        return None


class SQLAlchemySessionStore:
    """Opaque, server-side session storage. Only ever persists
    `sha256(raw_token)` -- the raw token exists solely as this class's
    return value and, at the web layer, a cookie value. Never logged, never
    stored.

    Production safety is instance-specific. An unbound factory cannot store
    sessions, and every SQLite URL is treated as development-only: in-memory
    databases are process-local, while file-backed SQLite does not provide the
    shared multi-worker deployment semantics this security contract promises.
    """

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        *,
        idle_timeout: timedelta = _DEFAULT_IDLE_TIMEOUT,
        absolute_timeout: timedelta = _DEFAULT_ABSOLUTE_TIMEOUT,
    ) -> None:
        _validate_session_lifetimes(idle_timeout, absolute_timeout)
        self._session_factory = session_factory
        self._idle_timeout = idle_timeout
        self._absolute_timeout = absolute_timeout
        bind = session_factory.kw.get("bind")
        dialect = getattr(bind, "dialect", None)
        dialect_name = getattr(dialect, "name", None)
        self.production_safe = isinstance(dialect_name, str) and dialect_name != "sqlite"

    async def create(self, principal: Principal) -> tuple[str, SessionRecord]:
        if principal.subject_id is None:
            raise ValueError("principal.subject_id is required to create a session")
        raw_token = secrets.token_urlsafe(32)
        now = datetime.now(UTC)
        row = SessionRow(
            token_hash=_hash_token(raw_token),
            user_id=int(principal.subject_id),
            created_at=now,
            last_seen_at=now,
            idle_expires_at=now + self._idle_timeout,
            absolute_expires_at=now + self._absolute_timeout,
        )
        async with self._session_factory() as session:
            session.add(row)
            await session.commit()
            await session.refresh(row)
        return raw_token, _to_record(row)

    async def resolve(self, raw_token: str) -> SessionRecord | None:
        token_hash = _hash_token(raw_token)
        now = datetime.now(UTC)
        async with self._session_factory() as session:
            row = (
                await session.execute(select(SessionRow).where(SessionRow.token_hash == token_hash))
            ).scalar_one_or_none()
            if row is None or row.revoked_at is not None:
                return None
            if now > _as_aware(row.idle_expires_at) or now > _as_aware(row.absolute_expires_at):
                return None
            row.last_seen_at = now
            row.idle_expires_at = now + self._idle_timeout
            await session.commit()
            await session.refresh(row)
            return _to_record(row)

    async def rotate(self, session_id: str) -> tuple[str, SessionRecord]:
        """Issue a genuinely new session (new session_id, new raw token),
        preserving the original absolute-expiry boundary, and revoke the
        previous session_id.

        A new session_id -- not just a new raw token on the same row -- is
        required so any CSRF token already issued (bound to session_id, not
        to the raw token) stops matching once the caller starts using the
        rotated session; reusing the old session_id would let a pre-rotation
        CSRF token remain valid forever. Preserving `absolute_expires_at`
        (rather than resetting it from "now") keeps rotation from being a
        way to keep a session alive indefinitely past its original absolute
        boundary.

        Only a *live* session rotates. Rotating a revoked or expired one
        would mint a brand-new valid credential out of a dead session --
        turning logout, an administrator's revocation, or a lapsed deadline
        back into access. The old row is revoked in the same transaction as
        the new row's insert, so a replay of the old session_id (two
        requests racing on one stolen cookie) cannot mint a second session.
        """
        numeric_id = _parse_session_id(session_id)
        if numeric_id is None:
            raise ValueError(f"unknown session_id: {session_id}")
        raw_token = secrets.token_urlsafe(32)
        now = datetime.now(UTC)
        async with self._session_factory() as session:
            old_row = await session.get(SessionRow, numeric_id)
            if old_row is None:
                raise ValueError(f"unknown session_id: {session_id}")
            if old_row.revoked_at is not None:
                raise ValueError(f"session is revoked: {session_id}")
            if now > _as_aware(old_row.idle_expires_at):
                raise ValueError(f"session is idle-expired: {session_id}")
            if now > _as_aware(old_row.absolute_expires_at):
                raise ValueError(f"session is expired: {session_id}")

            # Revoking the old row is the atomic claim on this rotation, so
            # it happens as a conditional UPDATE whose rowcount decides the
            # winner rather than as an attribute assignment. Two requests
            # racing on one stolen cookie both pass the checks above -- they
            # read before either writes -- and `SELECT ... FOR UPDATE` is not
            # portable (SQLite ignores it entirely). Predicating the write on
            # `revoked_at IS NULL` makes the database itself pick one winner
            # on every supported backend.
            claimed = await session.execute(
                update(SessionRow)
                .where(SessionRow.id == numeric_id, SessionRow.revoked_at.is_(None))
                .values(revoked_at=now)
            )
            if cast(CursorResult[Any], claimed).rowcount != 1:
                raise ValueError(f"session is revoked: {session_id}")

            new_row = SessionRow(
                token_hash=_hash_token(raw_token),
                user_id=old_row.user_id,
                created_at=now,
                last_seen_at=now,
                idle_expires_at=now + self._idle_timeout,
                absolute_expires_at=old_row.absolute_expires_at,
            )
            session.add(new_row)
            await session.commit()
            await session.refresh(new_row)
        return raw_token, _to_record(new_row)

    async def revoke(self, session_id: str) -> None:
        numeric_id = _parse_session_id(session_id)
        if numeric_id is None:
            return
        async with self._session_factory() as session:
            row = await session.get(SessionRow, numeric_id)
            if row is None:
                return
            row.revoked_at = datetime.now(UTC)
            await session.commit()
