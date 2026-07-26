import asyncio
from datetime import UTC, datetime, timedelta

import httpx
from rakit import Admin, SecretValue
from rakit_core.auth import Principal, SessionRecord
from rakit_web.security.rate_limit import LoginRateLimiter
from starlette.types import ASGIApp


class _ProductionSafeRateLimiter(LoginRateLimiter):
    """Real `LoginRateLimiter` behavior, self-declared `production_safe =
    True` -- these tests construct `Admin(debug=False, auth_backend=...)`
    and need a limiter Admin actually accepts in that mode. A real
    production deployment would use a genuinely shared-store
    implementation instead."""

    production_safe = True


class _LifespanDriver:
    """Local copy of conftest.py's LifespanDriver -- the tests directory is
    not a package, so it cannot be imported across test modules."""

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


class _FakeAuthBackend:
    async def authenticate(self, identifier: str, password: str) -> Principal | None:
        if identifier == "admin@example.com" and password == "correct-password":
            return Principal(
                subject_id="1",
                authenticated=True,
                permissions=frozenset({"operations.access"}),
            )
        return None

    async def resolve_principal(self, subject_id: str) -> Principal | None:
        if subject_id != "1":
            return None
        return Principal(
            subject_id="1",
            authenticated=True,
            permissions=frozenset({"operations.access"}),
        )


class _FakeSessionStore:
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
        return self._sessions.get(session_id) if session_id else None

    async def rotate(self, session_id: str) -> tuple[str, SessionRecord]:
        raise NotImplementedError

    async def revoke(self, session_id: str) -> None:
        self._sessions.pop(session_id, None)


def _auth_admin() -> Admin:
    return Admin(
        admin_id="operations",
        title="Operations",
        debug=False,
        secret_key=SecretValue("x" * 32),
        auth_backend=_FakeAuthBackend(),
        session_store=_FakeSessionStore(),
        login_rate_limiter=_ProductionSafeRateLimiter(),
    )


async def test_untrusted_host_is_rejected(client) -> None:
    response = await client.get("/", headers={"host": "evil.example"})
    assert response.status_code == 400


async def test_trusted_host_is_accepted(client) -> None:
    response = await client.get("/")
    assert response.status_code == 200


async def test_dynamic_response_has_security_headers(client) -> None:
    response = await client.get("/")
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert "frame-ancestors 'none'" in response.headers["content-security-policy"]
    assert response.headers["x-frame-options"] == "DENY"
    assert response.headers["referrer-policy"] == "same-origin"
    assert response.headers["cross-origin-opener-policy"] == "same-origin"


async def test_content_security_policy_disabled_omits_header() -> None:
    admin = Admin(title="Operations", debug=True, content_security_policy_enabled=False)
    app = admin.asgi()
    transport = httpx.ASGITransport(app=app)
    async with (
        _LifespanDriver(app),
        httpx.AsyncClient(transport=transport, base_url="http://localhost") as http_client,
    ):
        response = await http_client.get("/")
        assert "content-security-policy" not in response.headers


async def test_oversized_request_body_is_rejected(client) -> None:
    response = await client.post(
        "/",
        content=b"x" * (11 * 1024 * 1024),
        headers={"content-type": "application/x-www-form-urlencoded"},
    )
    assert response.status_code == 413


async def test_cross_origin_mutation_is_rejected() -> None:
    admin = _auth_admin()
    app = admin.asgi()
    transport = httpx.ASGITransport(app=app)
    async with (
        _LifespanDriver(app),
        httpx.AsyncClient(transport=transport, base_url="http://localhost") as http_client,
    ):
        response = await http_client.post(
            "/auth/login",
            data={"identifier": "admin@example.com", "password": "wrong"},
            headers={"origin": "http://evil.example"},
        )
        assert response.status_code == 403


async def test_same_origin_mutation_is_accepted() -> None:
    admin = _auth_admin()
    app = admin.asgi()
    transport = httpx.ASGITransport(app=app)
    async with (
        _LifespanDriver(app),
        httpx.AsyncClient(transport=transport, base_url="http://localhost") as http_client,
    ):
        page = await http_client.get("/auth/login")
        login_csrf = page.cookies["rakit_login_csrf"]
        http_client.cookies.set("rakit_login_csrf", login_csrf)
        response = await http_client.post(
            "/auth/login",
            data={
                "identifier": "admin@example.com",
                "password": "wrong",
                "login_csrf_token": login_csrf,
            },
            headers={"origin": "http://localhost"},
        )
        assert response.status_code == 401


async def test_mutation_with_no_origin_or_referer_is_accepted(client) -> None:
    """Not every legitimate client sends Origin/Referer (e.g. some non-browser
    API clients) -- only a *mismatched* Origin/Referer is rejected, absence
    is not treated as suspicious on its own (SameSite=Lax cookies are the
    primary CSRF defense; this header check is defense in depth)."""
    response = await client.post(
        "/",
        content=b"",
        headers={"content-type": "application/x-www-form-urlencoded"},
    )
    assert response.status_code != 403


async def test_null_origin_mutation_is_rejected() -> None:
    """A sandboxed cross-origin iframe (or some redirected requests) sends a
    literal `Origin: null` header -- `urlsplit("null").hostname` is `None`,
    which must NOT be treated the same as "no Origin/Referer sent at all."
    A *present but unresolvable* source is exactly the shape of value an
    attacker-controlled cross-origin request would send; it must be
    rejected, not silently passed through."""
    admin = _auth_admin()
    app = admin.asgi()
    transport = httpx.ASGITransport(app=app)
    async with (
        _LifespanDriver(app),
        httpx.AsyncClient(transport=transport, base_url="http://localhost") as http_client,
    ):
        response = await http_client.post(
            "/auth/login",
            data={"identifier": "admin@example.com", "password": "wrong"},
            headers={"origin": "null"},
        )
        assert response.status_code == 403


async def test_scheme_less_origin_mutation_is_rejected() -> None:
    """A malformed/scheme-less Origin value also resolves to `hostname is
    None` -- same rejection requirement as the null-origin case above."""
    admin = _auth_admin()
    app = admin.asgi()
    transport = httpx.ASGITransport(app=app)
    async with (
        _LifespanDriver(app),
        httpx.AsyncClient(transport=transport, base_url="http://localhost") as http_client,
    ):
        response = await http_client.post(
            "/auth/login",
            data={"identifier": "admin@example.com", "password": "wrong"},
            headers={"origin": "not-a-valid-origin"},
        )
        assert response.status_code == 403


async def _login_with_headers(headers: dict[str, str]) -> httpx.Response:
    """POST to login with the given headers, carrying a valid pre-session
    CSRF token so the *origin* check is what decides the outcome -- an
    accepted origin must reach the credential check (401 for the wrong
    password here), not be rejected 403 for a missing token."""
    admin = _auth_admin()
    app = admin.asgi()
    transport = httpx.ASGITransport(app=app)
    async with (
        _LifespanDriver(app),
        httpx.AsyncClient(transport=transport, base_url="http://localhost") as http_client,
    ):
        page = await http_client.get("/auth/login")
        login_csrf = page.cookies["rakit_login_csrf"]
        http_client.cookies.set("rakit_login_csrf", login_csrf)
        return await http_client.post(
            "/auth/login",
            data={
                "identifier": "admin@example.com",
                "password": "wrong",
                "login_csrf_token": login_csrf,
            },
            headers=headers,
        )


async def test_different_scheme_origin_is_rejected() -> None:
    """The request itself arrives over http://localhost (default port 80);
    an Origin claiming https on the same hostname must still be rejected --
    allowed-host validation only checks the *hostname*, but same-origin
    validation must also match scheme and effective port exactly."""
    response = await _login_with_headers({"origin": "https://localhost"})
    assert response.status_code == 403


async def test_different_explicit_port_origin_is_rejected() -> None:
    response = await _login_with_headers({"origin": "http://localhost:9999"})
    assert response.status_code == 403


async def test_different_scheme_and_port_origin_is_rejected() -> None:
    response = await _login_with_headers({"origin": "https://localhost:4443"})
    assert response.status_code == 403


async def test_exact_same_scheme_host_and_default_port_origin_is_accepted() -> None:
    response = await _login_with_headers({"origin": "http://localhost"})
    assert response.status_code == 401  # rejected for wrong password, not CSRF/origin


async def test_explicit_default_port_origin_is_accepted() -> None:
    """http://localhost:80 is the same effective origin as http://localhost
    -- an explicit default port must not be treated as a mismatch."""
    response = await _login_with_headers({"origin": "http://localhost:80"})
    assert response.status_code == 401


async def test_origin_case_is_normalized() -> None:
    response = await _login_with_headers({"origin": "HTTP://LOCALHOST"})
    assert response.status_code == 401


async def test_ipv4_host_origin_mismatch_is_rejected() -> None:
    """Same-origin validation compares against the request's own Host
    header, not just allowed_hosts -- a request that arrives with an IPv4
    Host must reject an Origin claiming a different IPv4 host."""
    admin = _auth_admin()
    app = admin.asgi()
    transport = httpx.ASGITransport(app=app)
    async with (
        _LifespanDriver(app),
        httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1") as http_client,
    ):
        response = await http_client.post(
            "/auth/login",
            data={"identifier": "admin@example.com", "password": "wrong"},
            headers={"origin": "http://127.0.0.2"},
        )
        assert response.status_code == 403


async def test_bracketed_ipv6_origin_matching_the_request_host_is_accepted() -> None:
    admin = _auth_admin()
    app = admin.asgi()
    transport = httpx.ASGITransport(app=app)
    async with (
        _LifespanDriver(app),
        httpx.AsyncClient(transport=transport, base_url="http://[::1]") as http_client,
    ):
        page = await http_client.get("/auth/login")
        login_csrf = page.cookies["rakit_login_csrf"]
        http_client.cookies.set("rakit_login_csrf", login_csrf)
        response = await http_client.post(
            "/auth/login",
            data={
                "identifier": "admin@example.com",
                "password": "wrong",
                "login_csrf_token": login_csrf,
            },
            headers={"origin": "http://[::1]"},
        )
        assert response.status_code == 401


async def test_referer_uses_the_same_canonical_comparison_as_origin() -> None:
    response = await _login_with_headers({"referer": "https://localhost:4443/auth/login"})
    assert response.status_code == 403


async def test_ipv6_loopback_host_is_trusted_by_default() -> None:
    """`SecurityConfig.allowed_hosts` defaults to including `"[::1]"`, but a
    naive `host.split(":")[0]` on the `Host` header turns `[::1]` into `[`,
    which never matches -- the bracketed IPv6-literal form must be preserved
    when stripping only an actual port suffix."""
    admin = Admin(title="Operations", debug=True)
    app = admin.asgi()
    transport = httpx.ASGITransport(app=app)
    async with (
        _LifespanDriver(app),
        httpx.AsyncClient(transport=transport, base_url="http://localhost") as http_client,
    ):
        response = await http_client.get("/", headers={"host": "[::1]"})
        assert response.status_code == 200

        response_with_port = await http_client.get("/", headers={"host": "[::1]:8000"})
        assert response_with_port.status_code == 200


# --- SecurityMiddleware's own rejections must carry security headers -----


def _assert_security_headers(response: httpx.Response) -> None:
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-frame-options"] == "DENY"
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["referrer-policy"] == "same-origin"
    assert response.headers["cross-origin-opener-policy"] == "same-origin"
    assert "frame-ancestors 'none'" in response.headers["content-security-policy"]


async def test_untrusted_host_rejection_still_carries_security_headers(client) -> None:
    """A response SecurityMiddleware generates itself must not skip the very
    headers that middleware exists to add -- otherwise its own error pages
    are the least protected responses the app can emit."""
    response = await client.get("/", headers={"host": "evil.example"})
    assert response.status_code == 400
    _assert_security_headers(response)


async def test_cross_origin_rejection_still_carries_security_headers() -> None:
    response = await _login_with_headers({"origin": "https://localhost:4443"})
    assert response.status_code == 403
    _assert_security_headers(response)


async def test_oversized_body_rejection_still_carries_security_headers(client) -> None:
    response = await client.post(
        "/",
        content=b"x" * (11 * 1024 * 1024),
        headers={"content-type": "application/x-www-form-urlencoded"},
    )
    assert response.status_code == 413
    _assert_security_headers(response)
