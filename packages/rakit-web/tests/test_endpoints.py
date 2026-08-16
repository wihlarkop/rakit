"""Typed custom endpoint regression coverage."""

from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from conftest import LifespanDriver
from pydantic import BaseModel
from rakit import (
    Admin,
    AdminEndpoint,
    EndpointAccessPolicy,
    EndpointContext,
    EndpointFileResult,
    EndpointMethod,
    EndpointResponseKind,
    EndpointResult,
    EndpointStreamResult,
    SecretValue,
)
from rakit_core.auth import Principal, SessionRecord
from rakit_core.crypto import TokenService
from rakit_core.di import ServiceScope
from rakit_core.errors import ErrorCode
from rakit_core.idempotency import IdempotencyReservation, IdempotencyStatus, OperationReceipt
from rakit_core.operations import current_operation_context
from rakit_core.transactions import OperationUnitOfWorkFactory, TransactionPolicy
from rakit_web.security.cookies import CSRF_COOKIE_NAME, SESSION_COOKIE_NAME
from rakit_web.security.csrf import CsrfService

_SECRET = SecretValue("x" * 32)


class _AuthBackend:
    def __init__(self, permissions: frozenset[str]) -> None:
        self.permissions = permissions

    async def authenticate(self, identifier: str, password: str) -> Principal | None:
        del identifier, password
        return None

    async def resolve_principal(self, subject_id: str) -> Principal | None:
        if subject_id != "operator":
            return None
        return Principal(
            subject_id="operator",
            authenticated=True,
            permissions=self.permissions,
        )


class _SessionStore:
    production_safe = True

    def __init__(self) -> None:
        now = datetime.now(UTC)
        self.record = SessionRecord(
            session_id="session-1",
            subject_id="operator",
            created_at=now,
            last_seen_at=now,
            idle_expires_at=now + timedelta(hours=1),
            absolute_expires_at=now + timedelta(days=1),
        )

    async def create(self, principal: Principal) -> tuple[str, SessionRecord]:
        del principal
        return "token", self.record

    async def resolve(self, raw_token: str) -> SessionRecord | None:
        return self.record if raw_token == "token" else None

    async def rotate(self, session_id: str) -> tuple[str, SessionRecord]:
        del session_id
        return "token", self.record

    async def revoke(self, session_id: str) -> None:
        del session_id


class _MemoryIdempotencyStore:
    production_safe = True

    def __init__(self) -> None:
        self._next_id = 1
        self._entries: dict[str, tuple[str, IdempotencyStatus, OperationReceipt | None, int]] = {}

    async def begin(self, token_hash: str, *, fingerprint: str) -> IdempotencyReservation:
        existing = self._entries.get(token_hash)
        if existing is not None:
            stored_fingerprint, status, receipt, reservation_id = existing
            if stored_fingerprint != fingerprint:
                raise ValueError("fingerprint mismatch")
            return IdempotencyReservation(
                reservation_id,
                status,
                completed_receipt=receipt,
                claimed=False,
            )
        reservation_id = self._next_id
        self._next_id += 1
        self._entries[token_hash] = (
            fingerprint,
            IdempotencyStatus.IN_PROGRESS,
            None,
            reservation_id,
        )
        return IdempotencyReservation(reservation_id, IdempotencyStatus.IN_PROGRESS)

    async def complete(
        self,
        reservation: IdempotencyReservation,
        receipt: OperationReceipt,
    ) -> None:
        for token_hash, (fingerprint, _status, _receipt, reservation_id) in tuple(
            self._entries.items()
        ):
            if reservation_id == reservation.reservation_id:
                self._entries[token_hash] = (
                    fingerprint,
                    IdempotencyStatus.COMPLETED,
                    receipt,
                    reservation_id,
                )
                return
        raise AssertionError("unknown reservation")

    async def release(self, reservation: IdempotencyReservation) -> None:
        for token_hash, entry in tuple(self._entries.items()):
            if entry[3] == reservation.reservation_id:
                del self._entries[token_hash]
                return

    async def fail_final(self, reservation: IdempotencyReservation) -> None:
        for token_hash, (fingerprint, _status, receipt, reservation_id) in tuple(
            self._entries.items()
        ):
            if reservation_id == reservation.reservation_id:
                self._entries[token_hash] = (
                    fingerprint,
                    IdempotencyStatus.FAILED_FINAL,
                    receipt,
                    reservation_id,
                )
                return


class _UnitOfWork:
    def __init__(self, factory: "_UnitOfWorkFactory", policy: TransactionPolicy) -> None:
        self.factory = factory
        self.policy = policy
        self.success = False

    async def mark_success(self) -> None:
        self.success = True

    async def commit(self) -> None:
        self.factory.commits += 1

    async def rollback(self, cause: BaseException | None = None) -> None:
        del cause
        self.factory.rollbacks += 1


class _UnitOfWorkFactory:
    def __init__(self) -> None:
        self.commits = 0
        self.rollbacks = 0

    @asynccontextmanager
    async def open(self, *, policy, event_publisher, operation_context):
        del event_publisher, operation_context
        unit = _UnitOfWork(self, policy)
        try:
            yield unit
        except BaseException as exc:
            await unit.rollback(exc)
            raise
        else:
            if unit.success:
                await unit.commit()
            else:
                await unit.rollback()


class _StatusInput(BaseModel):
    verbose: bool = False


class _StatusOutput(BaseModel):
    ok: bool
    verbose: bool


class _ChangeInput(BaseModel):
    value: int


class _ChangeOutput(BaseModel):
    accepted: int


def _private_admin(
    permissions: frozenset[str],
    *,
    store: _MemoryIdempotencyStore | None = None,
    uow_factory: _UnitOfWorkFactory | None = None,
) -> tuple[Admin, _SessionStore]:
    sessions = _SessionStore()
    admin = Admin(
        admin_id="ops",
        title="Operations",
        debug=True,
        secret_key=_SECRET,
        auth_backend=_AuthBackend(permissions),
        session_store=sessions,
        operation_idempotency_store=store,
    )
    if uow_factory is not None:
        admin.builder.registry.add_value(
            OperationUnitOfWorkFactory,
            uow_factory,
            scope=ServiceScope.APPLICATION,
        )
    return admin, sessions


def _client(app, *, authenticated: bool = False) -> httpx.AsyncClient:
    client = httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://localhost",
    )
    if authenticated:
        client.cookies.set(SESSION_COOKIE_NAME, "token")
    return client


def _csrf_token(admin: Admin, session: SessionRecord) -> str:
    token_service = TokenService.single_key(
        key_id="primary",
        value=_SECRET,
        admin_id=admin.config.admin_id,
    )
    return CsrfService(token_service).issue(session)


@pytest.mark.anyio
async def test_public_typed_get_query_success_and_operation_context() -> None:
    seen: list[tuple[str, bool]] = []
    admin = Admin(title="Operations", debug=True)

    @admin.api.get(
        "/api/status",
        endpoint_id="status",
        input_schema=_StatusInput,
        output_schema=_StatusOutput,
        access_policy=EndpointAccessPolicy.PUBLIC,
    )
    async def status(context: EndpointContext) -> EndpointResult[dict[str, bool]]:
        operation = current_operation_context()
        assert operation is not None
        assert isinstance(context.values, _StatusInput)
        seen.append((operation.operation, operation.services is not None))
        verbose = context.values.verbose
        return EndpointResult({"ok": True, "verbose": verbose})

    app = admin.asgi()
    async with LifespanDriver(app), _client(app) as client:
        response = await client.get("/api/status?verbose=true")

    assert response.status_code == 200
    assert response.json() == {"ok": True, "verbose": True}
    assert seen == [("endpoint:status", True)]


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("query", "issue_code"),
    (
        ("verbose=not-a-bool", "bool_parsing"),
        ("verbose=true&extra=1", "unknown_field"),
        ("verbose=true&verbose=false", "duplicate_field"),
    ),
)
async def test_get_query_validation_is_normalized(query: str, issue_code: str) -> None:
    admin = Admin(title="Operations", debug=True)

    @admin.api.get(
        "/api/status",
        input_schema=_StatusInput,
        access_policy=EndpointAccessPolicy.PUBLIC,
    )
    def status(_context: EndpointContext) -> EndpointResult[dict[str, bool]]:
        return EndpointResult({"ok": True})

    app = admin.asgi()
    async with LifespanDriver(app), _client(app) as client:
        response = await client.get(f"/api/status?{query}")

    payload = response.json()
    assert response.status_code == 422
    assert payload["error"]["code"] == ErrorCode.VALIDATION_FAILED
    assert issue_code in {issue["code"] for issue in payload["error"]["details"]["issues"]}


@pytest.mark.anyio
async def test_private_endpoint_uses_json_401_and_403_instead_of_browser_redirects() -> None:
    denied, _sessions = _private_admin(frozenset({"ops.access"}))

    @denied.api.get("/api/private")
    def private(_context: EndpointContext) -> EndpointResult[dict[str, bool]]:
        return EndpointResult({"ok": True})

    app = denied.asgi()
    async with LifespanDriver(app), _client(app) as anonymous:
        unauthenticated = await anonymous.get("/api/private")
    async with LifespanDriver(app), _client(app, authenticated=True) as authenticated:
        forbidden = await authenticated.get("/api/private")

    assert unauthenticated.status_code == 401
    assert unauthenticated.json()["error"]["code"] == ErrorCode.AUTH_UNAUTHENTICATED
    assert "location" not in unauthenticated.headers
    assert forbidden.status_code == 403
    assert forbidden.json()["error"]["code"] == ErrorCode.AUTH_FORBIDDEN


@pytest.mark.anyio
async def test_private_endpoint_exact_permission_succeeds() -> None:
    admin, _sessions = _private_admin(frozenset({"ops.endpoints.private.invoke"}))

    @admin.api.get("/api/private", endpoint_id="private")
    def private(_context: EndpointContext) -> EndpointResult[dict[str, bool]]:
        return EndpointResult({"ok": True})

    app = admin.asgi()
    async with LifespanDriver(app), _client(app, authenticated=True) as client:
        response = await client.get("/api/private")

    assert response.status_code == 200
    assert response.json() == {"ok": True}


@pytest.mark.anyio
async def test_public_status_is_exact_and_does_not_make_neighbor_path_public() -> None:
    admin, _sessions = _private_admin(frozenset())
    admin.register_endpoint(
        AdminEndpoint(
            endpoint_id="public_status",
            path="/api/status",
            method=EndpointMethod.GET,
            access_policy=EndpointAccessPolicy.PUBLIC,
            handler=lambda _context: EndpointResult({"public": True}),
        )
    )
    admin.register_endpoint(
        AdminEndpoint(
            endpoint_id="private_status_extra",
            path="/api/status-extra",
            method=EndpointMethod.GET,
            handler=lambda _context: EndpointResult({"private": True}),
        )
    )

    app = admin.asgi()
    async with LifespanDriver(app), _client(app) as client:
        public = await client.get("/api/status")
        private = await client.get("/api/status-extra")

    assert public.status_code == 200
    assert private.status_code == 401


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("content", "content_type", "expected_status", "issue_code"),
    (
        (b'{"value":', "application/json", 400, "invalid_json"),
        (b"[]", "application/json", 422, "object_required"),
        (b'{"value":1}', "text/plain", 400, "content_type"),
        (b'{"value":1,"extra":2}', "application/json", 422, "unknown_field"),
        (b'{"value":1,"value":2}', "application/json", 422, "duplicate_field"),
    ),
)
async def test_post_json_input_guardrails(
    content: bytes,
    content_type: str,
    expected_status: int,
    issue_code: str,
) -> None:
    store = _MemoryIdempotencyStore()
    admin, sessions = _private_admin(
        frozenset({"ops.endpoints.change.invoke"}),
        store=store,
    )

    @admin.api.post(
        "/api/change",
        endpoint_id="change",
        input_schema=_ChangeInput,
        output_schema=_ChangeOutput,
        transaction_policy=TransactionPolicy.DISABLED,
    )
    def change(context: EndpointContext) -> EndpointResult[dict[str, int]]:
        assert isinstance(context.values, _ChangeInput)
        return EndpointResult({"accepted": context.values.value})

    app = admin.asgi()
    csrf = _csrf_token(admin, sessions.record)
    async with LifespanDriver(app), _client(app, authenticated=True) as client:
        client.cookies.set(CSRF_COOKIE_NAME, csrf)
        response = await client.post(
            "/api/change",
            content=content,
            headers={
                "content-type": content_type,
                "x-csrf-token": csrf,
                "idempotency-key": "json-guardrail",
            },
        )

    assert response.status_code == expected_status
    issues = response.json()["error"]["details"]["issues"]
    assert issue_code in {issue["code"] for issue in issues}


@pytest.mark.anyio
async def test_post_requires_csrf_and_same_origin_before_handler_execution() -> None:
    calls = 0
    store = _MemoryIdempotencyStore()
    admin, sessions = _private_admin(
        frozenset({"ops.endpoints.change.invoke"}),
        store=store,
    )

    @admin.api.post(
        "/api/change",
        endpoint_id="change",
        input_schema=_ChangeInput,
        transaction_policy=TransactionPolicy.DISABLED,
    )
    def change(_context: EndpointContext) -> EndpointResult[dict[str, bool]]:
        nonlocal calls
        calls += 1
        return EndpointResult({"ok": True})

    app = admin.asgi()
    csrf = _csrf_token(admin, sessions.record)
    async with LifespanDriver(app), _client(app, authenticated=True) as client:
        client.cookies.set(CSRF_COOKIE_NAME, csrf)
        missing = await client.post(
            "/api/change",
            json={"value": 1},
            headers={"idempotency-key": "missing-csrf"},
        )
        cross_origin = await client.post(
            "/api/change",
            json={"value": 1},
            headers={
                "origin": "https://evil.example",
                "x-csrf-token": csrf,
                "idempotency-key": "cross-origin",
            },
        )

    assert missing.status_code == 403
    assert missing.json()["error"]["code"] == ErrorCode.AUTH_FORBIDDEN
    assert cross_origin.status_code == 403
    assert calls == 0


@pytest.mark.anyio
async def test_post_idempotency_replays_same_input_and_rejects_fingerprint_mismatch() -> None:
    calls = 0
    store = _MemoryIdempotencyStore()
    admin, sessions = _private_admin(
        frozenset({"ops.endpoints.change.invoke"}),
        store=store,
    )

    @admin.api.post(
        "/api/change",
        endpoint_id="change",
        input_schema=_ChangeInput,
        output_schema=_ChangeOutput,
        transaction_policy=TransactionPolicy.DISABLED,
    )
    def change(context: EndpointContext) -> EndpointResult[dict[str, int]]:
        nonlocal calls
        calls += 1
        assert isinstance(context.values, _ChangeInput)
        return EndpointResult({"accepted": context.values.value}, status_code=201)

    app = admin.asgi()
    csrf = _csrf_token(admin, sessions.record)
    headers = {"x-csrf-token": csrf, "idempotency-key": "request-1"}
    async with LifespanDriver(app), _client(app, authenticated=True) as client:
        client.cookies.set(CSRF_COOKIE_NAME, csrf)
        first = await client.post("/api/change", json={"value": 7}, headers=headers)
        replay = await client.post("/api/change", json={"value": 7}, headers=headers)
        mismatch = await client.post("/api/change", json={"value": 8}, headers=headers)

    assert first.status_code == replay.status_code == 201
    assert first.json() == replay.json() == {"accepted": 7}
    assert mismatch.status_code == 409
    assert calls == 1


@pytest.mark.anyio
async def test_post_auto_uses_root_uow_and_commits_success() -> None:
    factory = _UnitOfWorkFactory()
    store = _MemoryIdempotencyStore()
    seen_uow = False
    admin, sessions = _private_admin(
        frozenset({"ops.endpoints.change.invoke"}),
        store=store,
        uow_factory=factory,
    )

    @admin.api.post(
        "/api/change",
        endpoint_id="change",
        input_schema=_ChangeInput,
        output_schema=_ChangeOutput,
    )
    def change(context: EndpointContext) -> EndpointResult[dict[str, int]]:
        nonlocal seen_uow
        operation = current_operation_context()
        assert operation is not None
        seen_uow = operation.unit_of_work is not None
        assert isinstance(context.values, _ChangeInput)
        return EndpointResult({"accepted": context.values.value})

    app = admin.asgi()
    csrf = _csrf_token(admin, sessions.record)
    async with LifespanDriver(app), _client(app, authenticated=True) as client:
        client.cookies.set(CSRF_COOKIE_NAME, csrf)
        response = await client.post(
            "/api/change",
            json={"value": 9},
            headers={"x-csrf-token": csrf, "idempotency-key": "auto-success"},
        )

    assert response.status_code == 200
    assert seen_uow is True
    assert factory.commits == 1
    assert factory.rollbacks == 0


@pytest.mark.anyio
async def test_output_schema_is_enforced_before_response() -> None:
    admin = Admin(title="Operations", debug=True)

    @admin.api.get(
        "/api/status",
        output_schema=_StatusOutput,
        access_policy=EndpointAccessPolicy.PUBLIC,
    )
    def invalid(_context: EndpointContext) -> EndpointResult[dict[str, object]]:
        return EndpointResult({"ok": "not-a-bool", "verbose": False})

    app = admin.asgi()
    async with LifespanDriver(app), _client(app) as client:
        response = await client.get("/api/status")

    assert response.status_code == 500
    assert response.json()["error"]["code"] == ErrorCode.VALIDATION_FAILED


@pytest.mark.anyio
async def test_file_and_stream_escape_hatches_are_explicit_read_only_gets() -> None:
    admin = Admin(title="Operations", debug=True)
    admin.register_endpoint(
        AdminEndpoint(
            endpoint_id="download",
            path="/api/download",
            method=EndpointMethod.GET,
            access_policy=EndpointAccessPolicy.PUBLIC,
            response_kind=EndpointResponseKind.FILE,
            allow_response_escape_hatch=True,
            handler=lambda _context: EndpointFileResult(b"hello", "hello.txt", "text/plain"),
        )
    )

    async def chunks():
        yield b"a"
        yield b"b"

    admin.register_endpoint(
        AdminEndpoint(
            endpoint_id="stream",
            path="/api/stream",
            method=EndpointMethod.GET,
            access_policy=EndpointAccessPolicy.PUBLIC,
            response_kind=EndpointResponseKind.STREAM,
            allow_response_escape_hatch=True,
            handler=lambda _context: EndpointStreamResult(chunks(), "text/plain"),
        )
    )

    app = admin.asgi()
    async with LifespanDriver(app), _client(app) as client:
        file_response = await client.get("/api/download")
        stream_response = await client.get("/api/stream")

    assert file_response.status_code == 200
    assert file_response.content == b"hello"
    assert 'filename="hello.txt"' in file_response.headers["content-disposition"]
    assert stream_response.status_code == 200
    assert stream_response.content == b"ab"


def test_task7_configuration_guardrails_fail_closed() -> None:
    with pytest.raises(ValueError, match="Public POST"):
        AdminEndpoint(
            endpoint_id="unsafe_public_post",
            path="/api/public-write",
            method=EndpointMethod.POST,
            access_policy=EndpointAccessPolicy.PUBLIC,
            handler=lambda _context: EndpointResult({"ok": True}),
        )

    with pytest.raises(ValueError, match="escape hatch"):
        AdminEndpoint(
            endpoint_id="unsafe_stream",
            path="/api/stream",
            method=EndpointMethod.GET,
            response_kind=EndpointResponseKind.STREAM,
            handler=lambda _context: EndpointStreamResult((), "text/plain"),
        )

    admin = Admin(title="Operations", debug=True)
    admin.register_endpoint(
        AdminEndpoint(
            endpoint_id="status",
            path="/api/status",
            method=EndpointMethod.GET,
            access_policy=EndpointAccessPolicy.PUBLIC,
            handler=lambda _context: EndpointResult({"ok": True}),
        )
    )
    admin.compile()
    with pytest.raises(RuntimeError, match="after compilation"):
        admin.register_endpoint(
            AdminEndpoint(
                endpoint_id="late",
                path="/api/late",
                method=EndpointMethod.GET,
                access_policy=EndpointAccessPolicy.PUBLIC,
                handler=lambda _context: EndpointResult({"ok": True}),
            )
        )


def test_post_defaults_to_auto_and_get_defaults_to_read_only() -> None:
    get_endpoint = AdminEndpoint(
        endpoint_id="get",
        path="/get",
        method=EndpointMethod.GET,
        handler=lambda _context: EndpointResult({"ok": True}),
    )
    post_endpoint = AdminEndpoint(
        endpoint_id="post",
        path="/post",
        method=EndpointMethod.POST,
        handler=lambda _context: EndpointResult({"ok": True}),
    )

    assert get_endpoint.input_source is None
    assert get_endpoint.transaction_policy is TransactionPolicy.READ_ONLY
    assert post_endpoint.input_source is None
    assert post_endpoint.transaction_policy is TransactionPolicy.AUTO


@pytest.mark.anyio
async def test_form_post_success_uses_explicit_form_source() -> None:
    from rakit import EndpointInputSource

    store = _MemoryIdempotencyStore()
    admin, sessions = _private_admin(
        frozenset({"ops.endpoints.form_change.invoke"}),
        store=store,
    )

    @admin.api.post(
        "/api/form-change",
        endpoint_id="form_change",
        input_schema=_ChangeInput,
        input_source=EndpointInputSource.FORM,
        output_schema=_ChangeOutput,
        transaction_policy=TransactionPolicy.DISABLED,
    )
    def form_change(context: EndpointContext) -> EndpointResult[dict[str, int]]:
        assert isinstance(context.values, _ChangeInput)
        return EndpointResult({"accepted": context.values.value})

    app = admin.asgi()
    csrf = _csrf_token(admin, sessions.record)
    async with LifespanDriver(app), _client(app, authenticated=True) as client:
        client.cookies.set(CSRF_COOKIE_NAME, csrf)
        response = await client.post(
            "/api/form-change",
            data={"value": "11"},
            headers={"x-csrf-token": csrf, "idempotency-key": "form-success"},
        )

    assert response.status_code == 200
    assert response.json() == {"accepted": 11}


@pytest.mark.anyio
async def test_post_auto_rolls_back_when_handler_raises() -> None:
    factory = _UnitOfWorkFactory()
    store = _MemoryIdempotencyStore()
    admin, sessions = _private_admin(
        frozenset({"ops.endpoints.change.invoke"}),
        store=store,
        uow_factory=factory,
    )

    @admin.api.post(
        "/api/change",
        endpoint_id="change",
        input_schema=_ChangeInput,
    )
    def change(_context: EndpointContext) -> EndpointResult[dict[str, bool]]:
        raise RuntimeError("boom")

    app = admin.asgi()
    csrf = _csrf_token(admin, sessions.record)
    async with LifespanDriver(app), _client(app, authenticated=True) as client:
        client.cookies.set(CSRF_COOKIE_NAME, csrf)
        with pytest.raises(RuntimeError, match="boom"):
            await client.post(
                "/api/change",
                json={"value": 1},
                headers={"x-csrf-token": csrf, "idempotency-key": "rollback"},
            )

    assert factory.commits == 0
    assert factory.rollbacks == 1


@pytest.mark.anyio
async def test_mounted_admin_endpoint_keeps_root_path_and_exact_permission() -> None:
    from starlette.applications import Starlette
    from starlette.routing import Mount

    admin, _sessions = _private_admin(frozenset({"ops.endpoints.private.invoke"}))

    @admin.api.get("/api/private", endpoint_id="private")
    def private(_context: EndpointContext) -> EndpointResult[dict[str, bool]]:
        return EndpointResult({"ok": True})

    inner = admin.asgi()
    outer = Starlette(routes=[Mount("/admin", app=inner)])
    client = httpx.AsyncClient(
        transport=httpx.ASGITransport(app=outer),
        base_url="http://localhost",
    )
    client.cookies.set(SESSION_COOKIE_NAME, "token", path="/admin")

    async with LifespanDriver(inner), client:
        response = await client.get("/admin/api/private")

    assert response.status_code == 200
    assert response.json() == {"ok": True}
