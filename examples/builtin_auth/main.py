"""Deterministic built-in authentication example using only public Rakit imports."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from rakit import Admin, SecretValue
from rakit.core import Principal, SessionRecord


class DemoAuthBackend:
    """Development-only backend for learning the built-in login flow."""

    async def authenticate(self, identifier: str, password: str) -> Principal | None:
        if identifier.strip().lower() != "admin@example.com" or password != "demo-password":
            return None
        return Principal(
            subject_id="demo-admin",
            authenticated=True,
            display_name="Demo Admin",
            is_superuser=True,
        )

    async def resolve_principal(self, subject_id: str) -> Principal | None:
        if subject_id != "demo-admin":
            return None
        return Principal(
            subject_id="demo-admin",
            authenticated=True,
            display_name="Demo Admin",
            is_superuser=True,
        )


class DemoSessionStore:
    """In-memory, single-process session store. Never use this in production."""

    production_safe = False

    def __init__(self) -> None:
        self._records: dict[str, SessionRecord] = {}
        self._tokens: dict[str, str] = {}
        self._counter = 0

    async def create(self, principal: Principal) -> tuple[str, SessionRecord]:
        assert principal.subject_id is not None
        return self._new_session(principal.subject_id)

    async def resolve(self, raw_token: str) -> SessionRecord | None:
        session_id = self._tokens.get(raw_token)
        if session_id is None:
            return None
        record = self._records.get(session_id)
        if record is None or record.absolute_expires_at <= datetime.now(UTC):
            return None
        return record

    async def rotate(self, session_id: str) -> tuple[str, SessionRecord]:
        previous = self._records.pop(session_id)
        for token, stored_id in tuple(self._tokens.items()):
            if stored_id == session_id:
                self._tokens.pop(token, None)
        return self._new_session(previous.subject_id)

    async def revoke(self, session_id: str) -> None:
        self._records.pop(session_id, None)
        for token, stored_id in tuple(self._tokens.items()):
            if stored_id == session_id:
                self._tokens.pop(token, None)

    def _new_session(self, subject_id: str) -> tuple[str, SessionRecord]:
        self._counter += 1
        now = datetime.now(UTC)
        session_id = f"demo-session-{self._counter}"
        raw_token = f"demo-token-{self._counter}"
        record = SessionRecord(
            session_id=session_id,
            subject_id=subject_id,
            created_at=now,
            last_seen_at=now,
            idle_expires_at=now + timedelta(hours=1),
            absolute_expires_at=now + timedelta(hours=8),
        )
        self._records[session_id] = record
        self._tokens[raw_token] = session_id
        return raw_token, record


admin = Admin(
    admin_id="auth_demo",
    title="Built-in authentication demo",
    debug=True,
    secret_key=SecretValue("development-only-auth-example-key"),
    auth_backend=DemoAuthBackend(),
    session_store=DemoSessionStore(),
)

app = admin.asgi()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8000)
