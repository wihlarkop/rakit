"""Release-level security regressions spanning real Rakit middleware and runtimes."""

from __future__ import annotations

import asyncio
import re
from collections.abc import AsyncIterator, MutableMapping
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest
from rakit import ActionDefinition, ActionScope, ActionSuccess, Admin, ResourceAdmin, SecretValue
from rakit_core.actions import DomainActionExecutor
from rakit_core.auth import Principal, SessionRecord
from rakit_core.config import SecretValue as CoreSecretValue
from rakit_core.crypto import TokenService
from rakit_core.datasource import DataSourceCapabilities
from rakit_core.identity import IdentityCodec, RecordIdentity
from rakit_core.permissions import PermissionRequirement
from rakit_core.query import PageResult, ResourceQuery
from rakit_storage import TemporaryUpload
from rakit_storage_local import LocalStorage
from rakit_web.security.rate_limit import LoginRateLimiter
from sqlalchemy import update
from starlette.types import ASGIApp

from .rakit_integration import IntegrationApp, Order, client_for


class _RateLimiter(LoginRateLimiter):
    production_safe = True


class _MutableBackend:
    def __init__(self, permissions: frozenset[str]) -> None:
        self.permissions = permissions

    def principal(self) -> Principal:
        return Principal(
            subject_id="operator",
            authenticated=True,
            permissions=self.permissions,
        )

    async def authenticate(self, identifier: str, password: str) -> Principal | None:
        if (identifier, password) == ("operator@example.com", "password"):
            return self.principal()
        return None

    async def resolve_principal(self, subject_id: str) -> Principal | None:
        return self.principal() if subject_id == "operator" else None


class _SessionStore:
    production_safe = True

    def __init__(self) -> None:
        self.records: dict[str, SessionRecord] = {}
        self.tokens: dict[str, str] = {}

    async def create(self, principal: Principal) -> tuple[str, SessionRecord]:
        assert principal.subject_id is not None
        now = datetime.now(UTC)
        record = SessionRecord(
            session_id="release-session",
            subject_id=principal.subject_id,
            created_at=now,
            last_seen_at=now,
            idle_expires_at=now + timedelta(hours=1),
            absolute_expires_at=now + timedelta(days=1),
        )
        self.records[record.session_id] = record
        self.tokens["release-session-token"] = record.session_id
        return "release-session-token", record

    async def resolve(self, raw_token: str) -> SessionRecord | None:
        session_id = self.tokens.get(raw_token)
        return self.records.get(session_id) if session_id else None

    async def rotate(self, session_id: str) -> tuple[str, SessionRecord]:
        return "release-session-token", self.records[session_id]

    async def revoke(self, session_id: str) -> None:
        self.records.pop(session_id, None)


class _LifespanDriver:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app
        self.queue: asyncio.Queue[dict[str, str]] = asyncio.Queue()
        self.started = asyncio.Event()
        self.stopped = asyncio.Event()
        self.task: asyncio.Task[None] | None = None

    async def __aenter__(self) -> _LifespanDriver:
        async def receive() -> dict[str, str]:
            return await self.queue.get()

        async def send(message: MutableMapping[str, Any]) -> None:
            if message["type"].startswith("lifespan.startup"):
                self.started.set()
            elif message["type"].startswith("lifespan.shutdown"):
                self.stopped.set()

        async def run() -> None:
            await self.app({"type": "lifespan"}, receive, send)

        self.task = asyncio.create_task(run())
        await self.queue.put({"type": "lifespan.startup"})
        await self.started.wait()
        return self

    async def __aexit__(self, exc_type: object, exc: object, tb: object) -> None:
        await self.queue.put({"type": "lifespan.shutdown"})
        await self.stopped.wait()
        assert self.task is not None
        await self.task


class _Record:
    id = 1
    name = "Visible"
    secret = "do-not-query"


class _Source:
    capabilities = DataSourceCapabilities(read=True)
    fields = ("id", "name", "secret")
    identity_fields = ("id",)

    def identity_for(self, record: _Record) -> RecordIdentity:
        return RecordIdentity(values={"id": record.id})

    async def list(self, query: ResourceQuery) -> PageResult[_Record]:
        return PageResult(
            items=(_Record(),),
            page=query.pagination.page,
            per_page=query.pagination.per_page,
            has_previous=False,
            has_next=False,
            total_count=1,
        )

    async def count(self, query: ResourceQuery) -> int:
        return 1

    async def detail(self, identity: RecordIdentity) -> _Record | None:
        return _Record() if identity.values.get("id") in {1, "1"} else None


class _RecordsAdmin(ResourceAdmin):
    resource_id = "records"
    path = "/records"
    label = "Records"
    singular_label = "Record"
    list_fields = ("id", "name")
    detail_fields = ("id", "name")
    filter_fields = ("name",)
    data_source = _Source()


class _ExplodingSource(_Source):
    async def list(self, query: ResourceQuery) -> PageResult[_Record]:
        raise RuntimeError("sensitive-debug-marker")


class _ExplodingAdmin(_RecordsAdmin):
    resource_id = "exploding"
    path = "/exploding"
    data_source = _ExplodingSource()


async def _login(client: httpx.AsyncClient) -> str:
    page = await client.get("/auth/login")
    token = page.cookies["rakit_login_csrf"]
    client.cookies.set("rakit_login_csrf", token)
    response = await client.post(
        "/auth/login",
        data={
            "identifier": "operator@example.com",
            "password": "password",
            "login_csrf_token": token,
        },
        follow_redirects=False,
    )
    assert response.status_code == 303
    client.cookies.set("rakit_session", response.cookies["rakit_session"])
    csrf = response.cookies["rakit_csrf"]
    client.cookies.set("rakit_csrf", csrf)
    return csrf


def _tokens(html: str) -> dict[str, str]:
    return dict(re.findall(r'name="([^"]+)" value="([^"]*)"', html))


@pytest.mark.anyio
async def test_forged_csrf_is_rejected_by_real_login_route() -> None:
    backend = _MutableBackend(frozenset({"ops.access"}))
    admin = Admin(
        admin_id="ops",
        title="Ops",
        debug=True,
        secret_key=SecretValue("x" * 32),
        auth_backend=backend,
        session_store=_SessionStore(),
        login_rate_limiter=_RateLimiter(),
    )
    app = admin.asgi()
    async with (
        _LifespanDriver(app),
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://localhost"
        ) as client,
    ):
        response = await client.post(
            "/auth/login",
            data={
                "identifier": "operator@example.com",
                "password": "password",
                "login_csrf_token": "forged",
            },
        )
    assert response.status_code == 403


@pytest.mark.anyio
async def test_untrusted_host_and_forged_forwarded_host_fail_closed() -> None:
    admin = Admin(title="Ops", debug=True, allowed_hosts=("localhost",), trusted_proxies=())
    app = admin.asgi()
    async with (
        _LifespanDriver(app),
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://localhost"
        ) as client,
    ):
        assert (await client.get("/", headers={"host": "evil.example"})).status_code == 400
        forwarded = await client.get(
            "/",
            headers={
                "host": "localhost",
                "x-forwarded-host": "evil.example",
                "x-forwarded-proto": "https",
            },
        )
        assert forwarded.status_code == 200


@pytest.mark.anyio
async def test_stale_action_concurrency_is_rejected(
    integration: tuple[IntegrationApp, dict[str, object]], parent: str
) -> None:
    app, _ = integration
    async with client_for(app) as client:
        page = await client.get(f"/orders/{parent}/_actions/approve")
        tokens = _tokens(page.text)
        async with app.session_factory() as session:
            await session.execute(
                update(Order).where(Order.id == 10).values(version=Order.version + 1)
            )
            await session.commit()
        response = await client.post(
            f"/orders/{parent}/_actions/approve",
            data={
                "csrf_token": "csrf",
                "submission_token": tokens["submission_token"],
                "concurrency_token": tokens["concurrency_token"],
            },
            follow_redirects=False,
        )
    assert response.status_code == 409


@pytest.mark.anyio
async def test_idempotency_fingerprint_mismatch_fails_closed(
    integration: tuple[IntegrationApp, dict[str, object]],
) -> None:
    app, _ = integration
    await app.store.begin("same-token", fingerprint="payload-one")
    with pytest.raises(ValueError, match="fingerprint mismatch"):
        await app.store.begin("same-token", fingerprint="payload-two")


def test_expired_confirmation_token_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    import rakit_core.crypto as crypto

    service = TokenService.single_key(
        key_id="release",
        value=CoreSecretValue("x" * 32),
        admin_id="release",
    )
    issued_at = crypto.time.time()
    token = service.issue_in("confirmation", {"operation": "delete"}, timedelta(seconds=1))
    monkeypatch.setattr(crypto.time, "time", lambda: issued_at + 10)
    with pytest.raises(ValueError, match="expired"):
        service.verify(token, expected_purpose="confirmation")


@pytest.mark.anyio
async def test_sensitive_field_cannot_be_enabled_by_query_string() -> None:
    admin = Admin(title="Ops", debug=True)
    admin.register(_RecordsAdmin)
    app = admin.asgi()
    async with (
        _LifespanDriver(app),
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://localhost"
        ) as client,
    ):
        response = await client.get("/records", params={"filter": "secret:eq:do-not-query"})
    assert response.status_code in {400, 422}
    assert "do-not-query" not in response.text


@pytest.mark.anyio
async def test_local_storage_rejects_traversal_and_is_private_by_default(tmp_path: Any) -> None:
    storage = LocalStorage(storage_id="private", root=tmp_path, allowed_extensions=(".txt",))

    async def stream() -> AsyncIterator[bytes]:
        yield b"secret"

    upload = TemporaryUpload(
        original_name="secret.txt",
        content_type="text/plain",
        stream=stream,
        declared_size=6,
    )
    with pytest.raises(ValueError, match="prefix"):
        await storage.save(upload, prefix="../escape")

    stored = await storage.save(upload, prefix="safe")
    access = await storage.resolve_access(stored)
    assert access.public is False
    assert access.url is None


@pytest.mark.anyio
async def test_production_error_response_does_not_leak_traceback_marker() -> None:
    admin = Admin(
        title="Ops",
        debug=False,
        secret_key=SecretValue("x" * 32),
        allowed_hosts=("localhost",),
    )
    admin.register(_ExplodingAdmin)
    app = admin.asgi()
    async with (
        _LifespanDriver(app),
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app, raise_app_exceptions=False),
            base_url="http://localhost",
        ) as client,
    ):
        response = await client.get("/exploding")
    assert response.status_code == 500
    assert "sensitive-debug-marker" not in response.text
    assert "Traceback" not in response.text


@pytest.mark.anyio
async def test_permission_revocation_between_action_get_and_post_is_rechecked() -> None:
    action_permission = "ops.actions.deactivate.execute"
    backend = _MutableBackend(
        frozenset({"ops.access", "ops.resources.records.read", action_permission})
    )

    class ActionRecords(_RecordsAdmin):
        actions = (
            ActionDefinition(
                action_id="deactivate",
                label="Deactivate",
                scope=ActionScope.RECORD,
                resource_id="records",
                permission=PermissionRequirement.all_of(action_permission),
                executor=DomainActionExecutor(lambda _context: ActionSuccess()),
            ),
        )

    admin = Admin(
        admin_id="ops",
        title="Ops",
        debug=True,
        secret_key=SecretValue("x" * 32),
        auth_backend=backend,
        session_store=_SessionStore(),
        login_rate_limiter=_RateLimiter(),
    )
    admin.register(ActionRecords)
    encoded = IdentityCodec().encode(RecordIdentity(values={"id": 1}))
    app = admin.asgi()

    async with (
        _LifespanDriver(app),
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://localhost"
        ) as client,
    ):
        csrf = await _login(client)
        page = await client.get(f"/records/{encoded}/_actions/deactivate")
        assert page.status_code == 200
        submission = _tokens(page.text)["submission_token"]
        backend.permissions = frozenset({"ops.access", "ops.resources.records.read"})
        response = await client.post(
            f"/records/{encoded}/_actions/deactivate",
            data={"csrf_token": csrf, "submission_token": submission},
            follow_redirects=False,
        )
    assert response.status_code == 403
