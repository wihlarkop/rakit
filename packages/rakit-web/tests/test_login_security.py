import asyncio
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from rakit import Admin, SecretValue
from rakit_core.auth import Principal, SessionRecord
from starlette.types import ASGIApp

_KNOWN_USERS = {"admin@example.com": "correct-password"}


class _LifespanDriver:
    """Local copy of conftest.py's LifespanDriver: the tests directory is
    not a package (no __init__.py), so it cannot be imported across test
    modules -- see conftest.py for the full rationale on why the real ASGI
    lifespan protocol must be driven explicitly rather than relying on
    httpx.ASGITransport alone."""

    def __init__(self, app: ASGIApp) -> None:
        self._app = app
        self._receive_queue: asyncio.Queue = asyncio.Queue()
        self._startup_complete = asyncio.Event()
        self._shutdown_complete = asyncio.Event()
        self._startup_failure_message: str | None = None
        self._shutdown_failure_message: str | None = None
        self._task: asyncio.Task | None = None

    async def __aenter__(self) -> "_LifespanDriver":
        async def receive():
            return await self._receive_queue.get()

        async def send(message):
            if message["type"] == "lifespan.startup.complete":
                self._startup_complete.set()
            elif message["type"] == "lifespan.startup.failed":
                self._startup_failure_message = message.get("message", "")
                self._startup_complete.set()
            elif message["type"] == "lifespan.shutdown.complete":
                self._shutdown_complete.set()
            elif message["type"] == "lifespan.shutdown.failed":
                self._shutdown_failure_message = message.get("message", "")
                self._shutdown_complete.set()

        async def run_app() -> None:
            await self._app({"type": "lifespan"}, receive, send)

        self._task = asyncio.create_task(run_app())
        await self._receive_queue.put({"type": "lifespan.startup"})
        await self._startup_complete.wait()
        if self._startup_failure_message is not None:
            raise RuntimeError(f"ASGI lifespan startup failed: {self._startup_failure_message}")
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        await self._receive_queue.put({"type": "lifespan.shutdown"})
        await self._shutdown_complete.wait()
        assert self._task is not None
        await self._task
        if self._shutdown_failure_message is not None:
            raise RuntimeError(f"ASGI lifespan shutdown failed: {self._shutdown_failure_message}")


class FakeAuthBackend:
    """In-memory `AuthBackend` test double -- deliberately not
    `rakit-auth-sqlalchemy`'s implementation, so rakit-web's own test suite
    stays independent of any specific storage adapter."""

    async def authenticate(self, identifier: str, password: str) -> Principal | None:
        expected = _KNOWN_USERS.get(identifier)
        if expected is None or expected != password:
            return None
        return Principal(subject_id="1", authenticated=True, permissions=frozenset())


class FakeSessionStore:
    def __init__(self) -> None:
        self._sessions: dict[str, SessionRecord] = {}
        self._tokens: dict[str, str] = {}
        self._next_id = 1

    async def create(self, principal: Principal) -> tuple[str, SessionRecord]:
        assert principal.subject_id is not None
        session_id = str(self._next_id)
        self._next_id += 1
        raw_token = f"token-{session_id}"
        now = datetime.now(UTC)
        record = SessionRecord(
            session_id=session_id,
            subject_id=principal.subject_id,
            created_at=now,
            last_seen_at=now,
            idle_expires_at=now + timedelta(hours=1),
            absolute_expires_at=now + timedelta(days=1),
        )
        self._sessions[session_id] = record
        self._tokens[raw_token] = session_id
        return raw_token, record

    async def resolve(self, raw_token: str) -> SessionRecord | None:
        session_id = self._tokens.get(raw_token)
        if session_id is None:
            return None
        return self._sessions.get(session_id)

    async def rotate(self, session_id: str) -> tuple[str, SessionRecord]:
        record = self._sessions[session_id]
        new_token = f"token-{session_id}-rotated"
        self._tokens = {t: sid for t, sid in self._tokens.items() if sid != session_id}
        self._tokens[new_token] = session_id
        return new_token, record

    async def revoke(self, session_id: str) -> None:
        self._sessions.pop(session_id, None)
        self._tokens = {t: sid for t, sid in self._tokens.items() if sid != session_id}


@pytest.fixture
async def auth_client() -> AsyncIterator[httpx.AsyncClient]:
    admin = Admin(
        admin_id="operations",
        title="Operations",
        debug=False,
        secret_key=SecretValue("x" * 32),
        auth_backend=FakeAuthBackend(),
        session_store=FakeSessionStore(),
    )
    app = admin.asgi()
    transport = httpx.ASGITransport(app=app)
    async with (
        _LifespanDriver(app),
        httpx.AsyncClient(transport=transport, base_url="http://testserver") as http_client,
    ):
        yield http_client


async def test_unknown_user_and_wrong_password_share_message(auth_client) -> None:
    unknown = await auth_client.post(
        "/auth/login", data={"identifier": "missing@example.com", "password": "wrong"}
    )
    wrong = await auth_client.post(
        "/auth/login", data={"identifier": "admin@example.com", "password": "wrong"}
    )
    assert unknown.status_code == wrong.status_code == 401
    assert "Invalid credentials." in unknown.text
    assert "Invalid credentials." in wrong.text


async def test_successful_login_sets_session_and_csrf_cookies(auth_client) -> None:
    response = await auth_client.post(
        "/auth/login",
        data={"identifier": "admin@example.com", "password": "correct-password"},
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert "rakit_session" in response.cookies
    assert "rakit_csrf" in response.cookies


async def test_login_page_renders_without_a_session(auth_client) -> None:
    response = await auth_client.get("/auth/login")
    assert response.status_code == 200
    assert "Invalid credentials." not in response.text


async def test_logout_revokes_the_session(auth_client) -> None:
    login = await auth_client.post(
        "/auth/login",
        data={"identifier": "admin@example.com", "password": "correct-password"},
        follow_redirects=False,
    )
    raw_token = login.cookies["rakit_session"]
    auth_client.cookies.set("rakit_session", raw_token)

    logout = await auth_client.post("/auth/logout", follow_redirects=False)
    assert logout.status_code == 303
    assert logout.cookies.get("rakit_session") in (None, "")


async def test_repeated_failed_logins_are_rate_limited(auth_client) -> None:
    for _ in range(5):
        await auth_client.post(
            "/auth/login", data={"identifier": "admin@example.com", "password": "wrong"}
        )

    limited = await auth_client.post(
        "/auth/login", data={"identifier": "admin@example.com", "password": "wrong"}
    )
    assert limited.status_code == 429


async def test_login_response_is_not_cached() -> None:
    admin = Admin(
        admin_id="operations",
        title="Operations",
        debug=False,
        secret_key=SecretValue("x" * 32),
        auth_backend=FakeAuthBackend(),
        session_store=FakeSessionStore(),
    )
    app = admin.asgi()
    transport = httpx.ASGITransport(app=app)
    async with (
        _LifespanDriver(app),
        httpx.AsyncClient(transport=transport, base_url="http://testserver") as http_client,
    ):
        response = await http_client.get("/auth/login")
        assert response.headers.get("cache-control") == "no-store"
