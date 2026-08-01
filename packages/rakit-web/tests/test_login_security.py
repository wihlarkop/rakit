import asyncio
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from rakit import Admin, SecretValue
from rakit_core.auth import Principal, SessionRecord
from rakit_web.security.rate_limit import LoginRateLimiter
from starlette.types import ASGIApp

_KNOWN_USERS = {"admin@example.com": "correct-password"}


class _TestRateLimiter(LoginRateLimiter):
    """Real rate-limiting behavior (inherited unchanged from
    `LoginRateLimiter`), but self-declared `production_safe = True` --
    these tests intentionally construct `Admin(debug=False,
    auth_backend=...)` to exercise production-like secure-cookie behavior
    and (in `test_repeated_failed_logins_are_rate_limited`) real rate
    limiting, so they need a limiter `Admin` actually accepts in that mode.
    A real production deployment would use a genuinely shared-store
    implementation instead; this subclass exists only to satisfy the
    production-safety check in a single-process test."""

    production_safe = True


class _CapturingRateLimiter:
    production_safe = True

    def __init__(self) -> None:
        self.client_ips: list[str] = []

    def check(self, *, admin_id: str, identifier: str, client_ip: str) -> bool:
        self.client_ips.append(client_ip)
        return True


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
        return Principal(
            subject_id="1",
            authenticated=True,
            permissions=frozenset({"operations.access"}),
        )

    async def resolve_principal(self, subject_id: str) -> Principal | None:
        if subject_id != "1":
            return None
        return Principal(
            subject_id="1",
            authenticated=True,
            permissions=frozenset({"operations.access"}),
        )


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
        old_record = self._sessions[session_id]
        new_session_id = str(self._next_id)
        self._next_id += 1
        new_token = f"token-{new_session_id}"
        now = datetime.now(UTC)
        new_record = SessionRecord(
            session_id=new_session_id,
            subject_id=old_record.subject_id,
            created_at=now,
            last_seen_at=now,
            idle_expires_at=now + timedelta(hours=1),
            absolute_expires_at=old_record.absolute_expires_at,
        )
        self._sessions[new_session_id] = new_record
        self._tokens[new_token] = new_session_id
        await self.revoke(session_id)
        return new_token, new_record

    async def revoke(self, session_id: str) -> None:
        self._sessions.pop(session_id, None)
        self._tokens = {t: sid for t, sid in self._tokens.items() if sid != session_id}


async def _login(
    client: httpx.AsyncClient,
    *,
    prefix: str = "",
    identifier: str = "admin@example.com",
    password: str = "correct-password",
    headers: dict[str, str] | None = None,
) -> httpx.Response:
    """Fetch the login page to obtain a pre-session CSRF token, then submit
    it with the credentials -- the flow a real browser performs. Login
    requires this token (see `_verify_login_csrf`), so tests must not POST
    to `/auth/login` directly."""
    page = await client.get(f"{prefix}/auth/login")
    token = page.cookies["rakit_login_csrf"]
    client.cookies.set("rakit_login_csrf", token)
    return await client.post(
        f"{prefix}/auth/login",
        data={
            "identifier": identifier,
            "password": password,
            "login_csrf_token": token,
        },
        follow_redirects=False,
        headers=headers,
    )


@pytest.fixture
async def auth_client() -> AsyncIterator[httpx.AsyncClient]:
    admin = Admin(
        admin_id="operations",
        title="Operations",
        debug=False,
        secret_key=SecretValue("x" * 32),
        auth_backend=FakeAuthBackend(),
        session_store=FakeSessionStore(),
        login_rate_limiter=_TestRateLimiter(),
    )
    app = admin.asgi()
    transport = httpx.ASGITransport(app=app)
    async with (
        _LifespanDriver(app),
        httpx.AsyncClient(transport=transport, base_url="http://localhost") as http_client,
    ):
        yield http_client


async def test_unknown_user_and_wrong_password_share_message(auth_client) -> None:
    unknown = await _login(auth_client, identifier="missing@example.com", password="wrong")
    wrong = await _login(auth_client, identifier="admin@example.com", password="wrong")
    assert unknown.status_code == wrong.status_code == 401
    assert "Invalid credentials." in unknown.text
    assert "Invalid credentials." in wrong.text


async def test_successful_login_sets_session_and_csrf_cookies(auth_client) -> None:
    response = await _login(auth_client)
    assert response.status_code == 303
    assert "rakit_session" in response.cookies
    assert "rakit_csrf" in response.cookies


async def test_login_page_renders_without_a_session(auth_client) -> None:
    response = await auth_client.get("/auth/login")
    assert response.status_code == 200
    assert "Invalid credentials." not in response.text


async def test_logout_revokes_the_session(auth_client) -> None:
    login = await _login(auth_client)
    raw_token = login.cookies["rakit_session"]
    csrf_token = login.cookies["rakit_csrf"]
    auth_client.cookies.set("rakit_session", raw_token)
    auth_client.cookies.set("rakit_csrf", csrf_token)

    logout = await auth_client.post(
        "/auth/logout", data={"csrf_token": csrf_token}, follow_redirects=False
    )
    assert logout.status_code == 303
    assert logout.cookies.get("rakit_session") in (None, "")


async def test_logout_with_csrf_token_in_header_succeeds(auth_client) -> None:
    login = await _login(auth_client)
    raw_token = login.cookies["rakit_session"]
    csrf_token = login.cookies["rakit_csrf"]
    auth_client.cookies.set("rakit_session", raw_token)
    auth_client.cookies.set("rakit_csrf", csrf_token)

    logout = await auth_client.post(
        "/auth/logout", headers={"X-CSRF-Token": csrf_token}, follow_redirects=False
    )
    assert logout.status_code == 303


async def test_logout_without_a_csrf_token_is_rejected(auth_client) -> None:
    login = await _login(auth_client)
    raw_token = login.cookies["rakit_session"]
    csrf_token = login.cookies["rakit_csrf"]
    auth_client.cookies.set("rakit_session", raw_token)
    auth_client.cookies.set("rakit_csrf", csrf_token)

    logout = await auth_client.post("/auth/logout", follow_redirects=False)
    assert logout.status_code == 403

    # The session must still be active -- a rejected logout must not have
    # revoked anything. Proven by successfully logging out afterward with
    # the correct CSRF token, which only works against a still-live session.
    real_logout = await auth_client.post(
        "/auth/logout", data={"csrf_token": csrf_token}, follow_redirects=False
    )
    assert real_logout.status_code == 303


async def test_logout_with_a_mismatched_csrf_token_is_rejected(auth_client) -> None:
    login = await _login(auth_client)
    raw_token = login.cookies["rakit_session"]
    csrf_token = login.cookies["rakit_csrf"]
    auth_client.cookies.set("rakit_session", raw_token)
    auth_client.cookies.set("rakit_csrf", csrf_token)

    logout = await auth_client.post(
        "/auth/logout", data={"csrf_token": "not-the-real-token"}, follow_redirects=False
    )
    assert logout.status_code == 403


async def test_logout_with_a_csrf_token_from_a_different_session_is_rejected(auth_client) -> None:
    """The submitted/cookie CSRF token pair might match each other exactly
    (a forged double-submit pair from a different, attacker-controlled
    session) while still not being bound to *this* session -- CsrfService
    binds a token to the session_id it was issued for, so this must fail
    even though the double-submit values match one another."""
    first_login = await _login(auth_client)
    foreign_csrf_token = first_login.cookies["rakit_csrf"]

    second_login = await _login(auth_client)
    real_session_token = second_login.cookies["rakit_session"]
    auth_client.cookies.set("rakit_session", real_session_token)
    # Attacker submits a token bound to a *different* session, but sets it
    # as both the cookie and the submitted value so the double-submit
    # comparison alone would pass.
    auth_client.cookies.set("rakit_csrf", foreign_csrf_token)

    logout = await auth_client.post(
        "/auth/logout", data={"csrf_token": foreign_csrf_token}, follow_redirects=False
    )
    assert logout.status_code == 403


async def test_logout_without_any_active_session_is_a_safe_no_op(auth_client) -> None:
    """Logging out with no session cookie at all (already logged out, or
    never logged in) must not require a CSRF token -- there's no
    authenticated action to protect."""
    logout = await auth_client.post("/auth/logout", follow_redirects=False)
    assert logout.status_code == 303


async def test_repeated_failed_logins_are_rate_limited(auth_client) -> None:
    for _ in range(5):
        await _login(auth_client, password="wrong")

    limited = await _login(auth_client, password="wrong")
    assert limited.status_code == 429


async def test_production_limiter_receives_canonical_client_ip_from_trusted_chain() -> None:
    limiter = _CapturingRateLimiter()
    admin = Admin(
        admin_id="operations",
        title="Operations",
        debug=False,
        secret_key=SecretValue("x" * 32),
        auth_backend=FakeAuthBackend(),
        session_store=FakeSessionStore(),
        login_rate_limiter=limiter,
        trusted_proxies=("127.0.0.0/24",),
    )
    app = admin.asgi()
    transport = httpx.ASGITransport(app=app)
    async with (
        _LifespanDriver(app),
        httpx.AsyncClient(transport=transport, base_url="http://localhost") as client,
    ):
        response = await _login(
            client,
            password="wrong",
            headers={"x-forwarded-for": "2001:db8:0:0:0:0:0:1"},
        )
    assert response.status_code == 401
    assert limiter.client_ips == ["2001:db8::1"]


async def test_login_response_is_not_cached() -> None:
    admin = Admin(
        admin_id="operations",
        title="Operations",
        debug=False,
        secret_key=SecretValue("x" * 32),
        auth_backend=FakeAuthBackend(),
        session_store=FakeSessionStore(),
        login_rate_limiter=_TestRateLimiter(),
    )
    app = admin.asgi()
    transport = httpx.ASGITransport(app=app)
    async with (
        _LifespanDriver(app),
        httpx.AsyncClient(transport=transport, base_url="http://localhost") as http_client,
    ):
        response = await http_client.get("/auth/login")
        assert response.headers.get("cache-control") == "no-store"


def test_admin_rejects_development_rate_limiter_in_production_with_auth() -> None:
    """Integration-level proof (not just the unit-level validation
    function) that Admin itself refuses to construct with the bundled
    in-memory LoginRateLimiter when debug=False and auth is configured --
    the default limiter must never be silently accepted in that mode."""
    from rakit_core.errors import RakitError

    with pytest.raises(RakitError) as exc_info:
        Admin(
            admin_id="operations",
            title="Operations",
            debug=False,
            secret_key=SecretValue("x" * 32),
            auth_backend=FakeAuthBackend(),
            session_store=FakeSessionStore(),
            # No login_rate_limiter override -- Admin's own default
            # (the development-only LoginRateLimiter) must be rejected.
        )
    assert exc_info.value.details["reason"] == "development_only_rate_limiter"


def test_admin_rejects_auth_backend_without_session_store() -> None:
    from rakit_core.errors import RakitError

    with pytest.raises(RakitError):
        Admin(
            admin_id="operations",
            title="Operations",
            debug=True,
            auth_backend=FakeAuthBackend(),
        )


def test_admin_rejects_session_store_without_auth_backend() -> None:
    from rakit_core.errors import RakitError

    with pytest.raises(RakitError):
        Admin(
            admin_id="operations",
            title="Operations",
            debug=True,
            session_store=FakeSessionStore(),
        )


def test_admin_rejects_weak_production_secret_when_auth_is_configured() -> None:
    from rakit_core.errors import RakitError

    with pytest.raises(RakitError) as exc_info:
        Admin(
            admin_id="operations",
            title="Operations",
            debug=False,
            secret_key=SecretValue("too-short"),
            auth_backend=FakeAuthBackend(),
            session_store=FakeSessionStore(),
            login_rate_limiter=_TestRateLimiter(),
        )
    assert exc_info.value.details["reason"] == "weak_secret_key"


async def test_csrf_token_is_invalidated_after_session_rotation() -> None:
    """A CSRF token issued for a session must stop being valid for that
    same logical session's identity once the session is rotated -- since
    rotate() now issues a genuinely new session_id (see
    rakit_auth_sqlalchemy.sessions.rotate's docstring for the full
    rationale), CsrfService.verify() correctly rejects a pre-rotation token
    when checked against the post-rotation session_id."""
    from rakit_core.config import SecretValue
    from rakit_core.crypto import TokenService
    from rakit_web.security.csrf import CsrfService

    store = FakeSessionStore()
    principal = Principal(subject_id="1", authenticated=True)
    _raw_token, created = await store.create(principal)

    token_service = TokenService.single_key(
        key_id="k1", value=SecretValue("x" * 32), admin_id="operations"
    )
    csrf_service = CsrfService(token_service)
    pre_rotation_csrf = csrf_service.issue(created)

    _new_raw_token, rotated = await store.rotate(created.session_id)

    assert rotated.session_id != created.session_id
    assert csrf_service.verify(pre_rotation_csrf, session_id=created.session_id)
    assert not csrf_service.verify(pre_rotation_csrf, session_id=rotated.session_id)

    # A freshly issued token for the *new* session_id works correctly.
    post_rotation_csrf = csrf_service.issue(rotated)
    assert csrf_service.verify(post_rotation_csrf, session_id=rotated.session_id)


async def test_mounted_admin_login_logout_csrf_and_redirects_use_the_mount_prefix() -> None:
    """Cookie paths, redirect targets, and CSRF validation must all keep
    working correctly when Admin.asgi() is mounted under a path prefix
    (e.g. FastAPI's app.mount("/admin", admin.asgi())) -- not just at the
    application root."""
    from starlette.applications import Starlette
    from starlette.routing import Mount

    admin = Admin(
        admin_id="operations",
        title="Operations",
        debug=False,
        secret_key=SecretValue("x" * 32),
        auth_backend=FakeAuthBackend(),
        session_store=FakeSessionStore(),
        login_rate_limiter=_TestRateLimiter(),
    )
    child_app = admin.asgi()
    mounted_app = Starlette(routes=[Mount("/admin", app=child_app)])
    transport = httpx.ASGITransport(app=mounted_app)
    async with (
        _LifespanDriver(child_app),
        httpx.AsyncClient(transport=transport, base_url="http://localhost") as mounted_client,
    ):
        login = await _login(mounted_client, prefix="/admin")
        assert login.status_code == 303
        assert login.headers["location"] == "/admin/"
        raw_token = login.cookies["rakit_session"]
        csrf_token = login.cookies["rakit_csrf"]

        mounted_client.cookies.set("rakit_session", raw_token)
        mounted_client.cookies.set("rakit_csrf", csrf_token)

        logout = await mounted_client.post(
            "/admin/auth/logout", data={"csrf_token": csrf_token}, follow_redirects=False
        )
        assert logout.status_code == 303
        assert logout.headers["location"] == "/admin/auth/login"


# --- Login POST needs its own CSRF defense ------------------------------


async def test_login_post_without_origin_or_csrf_token_is_rejected(auth_client) -> None:
    """`/auth/login` is the only unauthenticated state-changing endpoint.
    SecurityMiddleware's origin check deliberately allows a request sending
    neither Origin nor Referer, so login needs its own pre-session CSRF
    token as a second line of defence -- otherwise a login-CSRF (forcing a
    victim into the attacker's session) has nothing stopping it from a
    client that omits both headers."""
    # Deliberately a raw POST -- no login page fetched, no token submitted,
    # no Origin/Referer -- i.e. exactly what a forged cross-site login
    # request looks like from a client that sends neither header.
    response = await auth_client.post(
        "/auth/login",
        data={"identifier": "admin@example.com", "password": "correct-password"},
        follow_redirects=False,
    )
    assert response.status_code == 403
    assert "rakit_session" not in response.cookies


async def test_login_page_issues_a_pre_session_csrf_token(auth_client) -> None:
    page = await auth_client.get("/auth/login")
    assert page.status_code == 200
    assert "rakit_login_csrf" in page.cookies
    # The token is embedded in the form so a normal browser submission
    # carries it back without any JavaScript.
    assert 'name="login_csrf_token"' in page.text


async def test_login_succeeds_with_the_issued_pre_session_token(auth_client) -> None:
    page = await auth_client.get("/auth/login")
    token = page.cookies["rakit_login_csrf"]
    auth_client.cookies.set("rakit_login_csrf", token)

    response = await auth_client.post(
        "/auth/login",
        data={
            "identifier": "admin@example.com",
            "password": "correct-password",
            "login_csrf_token": token,
        },
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert "rakit_session" in response.cookies


async def test_login_with_a_mismatched_pre_session_token_is_rejected(auth_client) -> None:
    page = await auth_client.get("/auth/login")
    auth_client.cookies.set("rakit_login_csrf", page.cookies["rakit_login_csrf"])

    response = await auth_client.post(
        "/auth/login",
        data={
            "identifier": "admin@example.com",
            "password": "correct-password",
            "login_csrf_token": "not-the-issued-token",
        },
        follow_redirects=False,
    )
    assert response.status_code == 403
