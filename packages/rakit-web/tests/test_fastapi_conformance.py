"""D4.2 proof that a real FastAPI host composes through the generic ASGI root."""

from collections.abc import AsyncIterator, Awaitable, Callable, Mapping
from contextlib import asynccontextmanager
from typing import Any, cast

import pytest
from rakit import Admin, ResourceAdmin, compose_asgi
from rakit_core.datasource import DataSourceCapabilities
from rakit_core.pagination import PageResult
from rakit_core.query import ResourceQuery
from rakit_web.lifecycle import RuntimeState
from starlette.testclient import TestClient
from starlette.types import ASGIApp, Message, Receive, Scope, Send


class _EmptyDataSource:
    capabilities = DataSourceCapabilities()
    fields = ("id",)
    identity_fields = ("id",)

    async def list(self, _query: ResourceQuery) -> PageResult[dict[str, int]]:
        return PageResult(
            items=(),
            page=1,
            per_page=25,
            has_previous=False,
            has_next=False,
            total_count=0,
        )

    async def count(self, _query: ResourceQuery) -> int:
        return 0

    async def detail(self, _identity: object) -> dict[str, int]:
        return {"id": 1}


class _RecordsAdmin(ResourceAdmin):
    resource_id = "records"
    path = "/records"
    label = "Records"
    singular_label = "Record"
    list_fields = ("id",)
    detail_fields = ("id",)
    data_source = _EmptyDataSource()


def _build_admin() -> Admin:
    """Build the host-independent Rakit application definition."""

    admin = Admin(
        title="D4.2 FastAPI proof",
        debug=True,
        allowed_hosts=("localhost",),
    )
    admin.register(_RecordsAdmin)
    return admin


def _compose(host: ASGIApp, admin: object) -> ASGIApp:
    """Keep host-framework ASGI type aliases at this test-only seam."""

    return compose_asgi(host, admin, path="/admin")


class _FastAPIHostMarker:
    """Add a marker only while serving through FastAPI's host branch."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def marked_send(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                headers.append((b"x-fastapi-host-middleware", b"1"))
                message = {**message, "headers": headers}
            await send(message)

        await self.app(scope, receive, marked_send)


class _RecordingAdmin:
    """Test-only boundary recorder around a real Admin ASGI child."""

    def __init__(self, admin: Admin) -> None:
        self.admin = admin
        self.scopes: list[dict[str, Any]] = []

    def on_startup(self, callback: Callable[[], Awaitable[None]]) -> Callable[[], Awaitable[None]]:
        return self.admin.on_startup(callback)

    def on_shutdown(self, callback: Callable[[], Awaitable[None]]) -> Callable[[], Awaitable[None]]:
        return self.admin.on_shutdown(callback)

    def asgi(self) -> ASGIApp:
        child = self.admin.asgi()

        async def recording_child(scope: Scope, receive: Receive, send: Send) -> None:
            if scope["type"] in {"http", "websocket"}:
                snapshot = dict(scope)
                state = scope.get("state")
                if isinstance(state, Mapping):
                    snapshot["state"] = dict(state)
                self.scopes.append(snapshot)
            await child(scope, receive, send)

        return recording_child


class _RecordingHost:
    """Record the host branch before the real FastAPI app sees a scope."""

    def __init__(self, host: ASGIApp) -> None:
        self.host = host
        self.scopes: list[dict[str, Any]] = []

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] in {"http", "websocket"}:
            snapshot = dict(scope)
            state = scope.get("state")
            if isinstance(state, Mapping):
                snapshot["state"] = dict(state)
            self.scopes.append(snapshot)
        await self.host(scope, receive, send)


def _build_host(
    events: list[str],
    counters: dict[str, int] | None = None,
    *,
    fail_startup: bool = False,
) -> ASGIApp:
    """Build a real FastAPI host with only host-local semantics."""

    from fastapi import Depends, FastAPI, HTTPException, Request, WebSocket
    from fastapi.responses import JSONResponse
    from pydantic import BaseModel

    counts = counters if counters is not None else {}

    class HostItem(BaseModel):
        owner: str
        item_id: int
        query: str
        dependency: str
        host_state: str
        scope_state: str
        root_path: str

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[dict[str, str]]:
        events.append("fastapi.startup")
        if fail_startup:
            raise RuntimeError("fastapi startup failed")
        app.state.host_value = "fastapi-host-state"
        try:
            yield {"fastapi.lifespan": "present"}
        finally:
            events.append("fastapi.shutdown")

    host = FastAPI(lifespan=lifespan)

    async def host_dependency(request: Request) -> str:
        counts["dependency"] = counts.get("dependency", 0) + 1
        return request.app.state.host_value

    async def require_host_token(request: Request) -> None:
        counts["security"] = counts.get("security", 0) + 1
        if request.headers.get("authorization") != "Bearer host-token":
            raise HTTPException(status_code=401, detail="fastapi host authentication required")

    @host.get("/api/items/{item_id}", response_model=HostItem)
    async def host_item(
        request: Request,
        item_id: int,
        q: str,
        dependency: str = Depends(host_dependency),
    ) -> dict[str, object]:
        return {
            "owner": "fastapi",
            "item_id": item_id,
            "query": q,
            "dependency": dependency,
            "host_state": request.app.state.host_value,
            "scope_state": request.scope["state"]["fastapi.lifespan"],
            "root_path": request.scope["root_path"],
            "discarded_by_response_model": "not exposed",
        }

    @host.get("/protected", dependencies=[Depends(require_host_token)])
    async def protected() -> dict[str, object]:
        return {"owner": "fastapi", "protected": True}

    @host.get("/host-error")
    async def host_error() -> object:
        raise HTTPException(status_code=418, detail="fastapi-owned")

    @host.get("/{host_path:path}")
    async def host_fallback(host_path: str) -> dict[str, str]:
        return {"owner": "fastapi", "host_path": host_path}

    @host.websocket("/ws")
    async def host_websocket(websocket: WebSocket) -> None:
        await websocket.accept()
        await websocket.send_text("fastapi-ready")

    @host.exception_handler(HTTPException)
    async def host_exception_handler(_request: Request, exc: HTTPException) -> JSONResponse:
        return JSONResponse(
            {
                "owner": "fastapi",
                "handled": "fastapi-exception-handler",
                "detail": exc.detail,
            },
            status_code=exc.status_code,
        )

    host.add_middleware(_FastAPIHostMarker)
    return host


def test_real_fastapi_routes_preserve_host_and_rakit_semantics() -> None:
    events: list[str] = []
    admin = _build_admin()
    recorded_admin = _RecordingAdmin(admin)
    recorded_host = _RecordingHost(_build_host(events))
    app = _compose(recorded_host, recorded_admin)

    with TestClient(cast(Any, app), base_url="http://localhost") as client:
        host = client.get("/api/items/42", params={"q": "preserved"})
        rakit_root = client.get("/admin")
        rakit_descendant = client.get("/admin/_system/health")
        false_boundary = client.get("/administrator")

    assert host.status_code == 200
    assert host.json() == {
        "owner": "fastapi",
        "item_id": 42,
        "query": "preserved",
        "dependency": "fastapi-host-state",
        "host_state": "fastapi-host-state",
        "scope_state": "present",
        "root_path": "",
    }
    assert host.headers["x-fastapi-host-middleware"] == "1"
    assert rakit_root.status_code == 200
    assert "D4.2 FastAPI proof" in rakit_root.text
    assert rakit_descendant.status_code == 200
    assert rakit_descendant.json() == {"status": "ok"}
    assert false_boundary.status_code == 200
    assert false_boundary.json()["owner"] == "fastapi"
    assert "x-fastapi-host-middleware" not in rakit_root.headers
    host_scope = next(scope for scope in recorded_host.scopes if scope["path"] == "/api/items/42")
    assert host_scope["root_path"] == ""
    assert host_scope["query_string"] == b"q=preserved"
    assert host_scope["state"] == {"fastapi.lifespan": "present"}
    assert len(recorded_admin.scopes) == 2
    assert all(
        scope["path"] not in {"/admin", "/admin/_system/health"} for scope in recorded_admin.scopes
    )
    assert all("fastapi.lifespan" not in scope.get("state", {}) for scope in recorded_admin.scopes)


def test_fastapi_depends_and_security_do_not_run_for_rakit() -> None:
    events: list[str] = []
    counters: dict[str, int] = {}
    admin = _build_admin()
    app = _compose(_build_host(events, counters), admin)

    with TestClient(cast(Any, app), base_url="http://localhost") as client:
        host = client.get("/api/items/7", params={"q": "dependency"})
        assert host.status_code == 200
        assert counters == {"dependency": 1}

        unauthorized = client.get("/protected")
        assert unauthorized.status_code == 401
        assert counters == {"dependency": 1, "security": 1}

        authorized = client.get("/protected", headers={"authorization": "Bearer host-token"})
        assert authorized.status_code == 200
        assert authorized.json() == {"owner": "fastapi", "protected": True}
        assert counters == {"dependency": 1, "security": 2}

        rakit = client.get("/admin/_system/health")

    assert rakit.status_code == 200
    assert counters == {"dependency": 1, "security": 2}


def test_fastapi_middleware_and_exception_handler_are_host_local() -> None:
    events: list[str] = []
    admin = _build_admin()
    app = _compose(_build_host(events), admin)

    with TestClient(cast(Any, app), base_url="http://localhost") as client:
        host_error = client.get("/host-error")
        rakit_error = client.get("/admin/not-a-rakit-route")

    assert host_error.status_code == 418
    assert host_error.json() == {
        "owner": "fastapi",
        "handled": "fastapi-exception-handler",
        "detail": "fastapi-owned",
    }
    assert host_error.headers["x-fastapi-host-middleware"] == "1"
    assert rakit_error.status_code == 404
    assert "fastapi-exception-handler" not in rakit_error.text
    assert "x-fastapi-host-middleware" not in rakit_error.headers


def test_real_fastapi_and_rakit_lifecycles_run_once_in_composition_order() -> None:
    events: list[str] = []
    admin = _build_admin()

    async def rakit_startup() -> None:
        events.append("rakit.startup")

    async def rakit_shutdown() -> None:
        events.append("rakit.shutdown")

    admin.on_startup(rakit_startup)
    admin.on_shutdown(rakit_shutdown)
    app = _compose(_build_host(events), admin)

    with TestClient(cast(Any, app), base_url="http://localhost"):
        assert events == ["fastapi.startup", "rakit.startup"]

    assert events == [
        "fastapi.startup",
        "rakit.startup",
        "rakit.shutdown",
        "fastapi.shutdown",
    ]


def test_fastapi_startup_failure_does_not_start_rakit() -> None:
    events: list[str] = []
    admin = _build_admin()

    async def rakit_startup() -> None:
        events.append("rakit.startup")

    admin.on_startup(rakit_startup)
    app = _compose(_build_host(events, fail_startup=True), admin)

    with (
        pytest.raises(Exception, match="fastapi startup failed"),
        TestClient(cast(Any, app), base_url="http://localhost"),
    ):
        pass

    assert events == ["fastapi.startup"]
    assert admin.lifecycle.state is RuntimeState.CREATED


def test_rakit_startup_failure_rolls_fastapi_back() -> None:
    events: list[str] = []
    admin = _build_admin()

    async def rakit_startup() -> None:
        events.append("rakit.startup")
        raise RuntimeError("rakit startup failed")

    admin.on_startup(rakit_startup)
    app = _compose(_build_host(events), admin)

    with (
        pytest.raises(Exception, match="rakit startup failed"),
        TestClient(cast(Any, app), base_url="http://localhost"),
    ):
        pass

    assert events == ["fastapi.startup", "rakit.startup", "fastapi.shutdown"]
    assert admin.lifecycle.state is RuntimeState.FAILED


def test_real_fastapi_root_path_forms_preserve_composition_ownership_and_state() -> None:
    events: list[str] = []
    admin = _build_admin()
    recorded_admin = _RecordingAdmin(admin)
    recorded_host = _RecordingHost(_build_host(events))
    app = _compose(recorded_host, recorded_admin)

    with TestClient(cast(Any, app), base_url="http://localhost", root_path="/proxy") as client:
        host_separate = client.get("/api/items/7", params={"q": "separate"})
        rakit_separate = client.get("/admin/_system/ready")
        host_included = client.get("/proxy/api/items/8", params={"q": "included"})
        rakit_included = client.get("/proxy/admin/_system/ready")
        administrator = client.get("/administrator")
        proxy_two = client.get("/proxy2/admin")

    assert host_separate.json()["owner"] == "fastapi"
    assert host_separate.json()["root_path"] == "/proxy"
    assert host_included.json()["owner"] == "fastapi"
    assert host_included.json()["item_id"] == 8
    assert host_included.json()["root_path"] == "/proxy"
    assert rakit_separate.json() == {"status": "ready"}
    assert rakit_included.json() == {"status": "ready"}
    assert administrator.json()["owner"] == "fastapi"
    assert proxy_two.json()["owner"] == "fastapi"

    separate_scope = next(
        scope for scope in recorded_host.scopes if scope["path"] == "/api/items/7"
    )
    assert separate_scope["root_path"] == "/proxy"
    assert separate_scope["state"] == {"fastapi.lifespan": "present"}
    included_scope = next(
        scope for scope in recorded_host.scopes if scope["path"] == "/proxy/api/items/8"
    )
    assert included_scope["root_path"] == "/proxy"
    assert included_scope["state"] == {"fastapi.lifespan": "present"}
    proxy_two_scope = next(
        scope for scope in recorded_host.scopes if scope["path"] == "/proxy2/admin"
    )
    assert proxy_two_scope["root_path"] == "/proxy"
    assert proxy_two_scope["raw_path"] == b"/proxy2/admin"
    assert len(recorded_admin.scopes) == 2
    assert all(scope["root_path"] == "/proxy/admin" for scope in recorded_admin.scopes)
    assert all("fastapi.lifespan" not in scope.get("state", {}) for scope in recorded_admin.scopes)


def test_fastapi_openapi_docs_and_websocket_remain_host_owned() -> None:
    events: list[str] = []
    admin = _build_admin()
    app = _compose(_build_host(events), admin)

    with (
        TestClient(cast(Any, app), base_url="http://localhost") as client,
        client.websocket_connect("/ws") as websocket,
    ):
        websocket_text = websocket.receive_text()
        openapi = client.get("/openapi.json")
        docs = client.get("/docs")

    assert websocket_text == "fastapi-ready"
    assert openapi.status_code == 200
    paths = openapi.json()["paths"]
    assert "/api/items/{item_id}" in paths
    assert not any(path == "/admin" or path.startswith("/admin/") for path in paths)
    assert docs.status_code == 200
    assert docs.headers["content-type"].startswith("text/html")
