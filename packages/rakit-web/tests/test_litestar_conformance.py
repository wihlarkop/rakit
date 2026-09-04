"""D4.1 proof that a real Litestar host composes through the generic ASGI root."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from typing import Any, cast

import pytest
from litestar import Litestar, Request, get, websocket_listener
from litestar.datastructures import State
from litestar.exceptions import HTTPException
from litestar.params import FromPath
from litestar.testing import TestClient
from rakit import Admin, ResourceAdmin, compose_asgi
from rakit_core.datasource import DataSourceCapabilities
from rakit_core.pagination import PageResult
from rakit_core.query import ResourceQuery
from rakit_web.lifecycle import RuntimeState
from starlette.types import ASGIApp, Message, Receive, Scope, Send

pytestmark = pytest.mark.filterwarnings("ignore:The base_url.*:UserWarning")


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
    """Build the same Rakit application definition for every host test."""

    admin = Admin(
        title="D4.1 Litestar proof",
        debug=True,
        allowed_hosts=("localhost",),
    )
    admin.register(_RecordsAdmin)
    return admin


def _compose(host: Litestar, admin: object) -> ASGIApp:
    """Keep incompatible framework ASGI type aliases at this test seam."""

    return compose_asgi(cast(ASGIApp, host), admin, path="/admin")


class _HostMarkerMiddleware:
    """Add a marker only while serving through Litestar's host branch."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def marked_send(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                headers.append((b"x-litestar-host-middleware", b"1"))
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


def _build_host(
    events: list[str],
    *,
    fail_startup: bool = False,
) -> Litestar:
    @get("/host")
    async def host_route(request: Request[Any, Any, Any]) -> dict[str, object]:
        host_state = request.app.state.get("litestar.host")
        return {
            "owner": "litestar",
            "query": request.query_params.get("q"),
            "has_litestar_app": "litestar_app" in request.scope,
            "host_state": host_state,
        }

    @get("/host-error")
    async def host_error() -> object:
        raise HTTPException(status_code=418, detail="litestar-owned")

    @get("/{host_path:path}")
    async def host_fallback(host_path: FromPath[str]) -> dict[str, str]:
        return {"owner": "litestar", "host_path": host_path}

    @websocket_listener("/ws")
    async def host_websocket(data: str) -> str:
        return f"litestar:{data}"

    async def startup() -> None:
        events.append("litestar.startup")
        if fail_startup:
            raise RuntimeError("litestar startup failed")

    async def shutdown() -> None:
        events.append("litestar.shutdown")

    return Litestar(
        route_handlers=[host_route, host_error, host_fallback, host_websocket],
        middleware=[cast(Any, _HostMarkerMiddleware)],
        on_startup=[startup],
        on_shutdown=[shutdown],
        state=State({"litestar.host": "present"}),
    )


def test_real_litestar_routes_host_and_rakit_ownership_without_registration_branching() -> None:
    events: list[str] = []
    admin = _build_admin()
    recorded_admin = _RecordingAdmin(admin)
    app = _compose(_build_host(events), recorded_admin)

    with TestClient(cast(Any, app), base_url="http://localhost") as client:
        host = client.get("/host", params={"q": "preserved"})
        rakit_root = client.get("/admin")
        rakit_descendant = client.get("/admin/_system/health")
        false_boundary = client.get("/administrator")

    assert host.status_code == 200
    assert host.json() == {
        "owner": "litestar",
        "query": "preserved",
        "has_litestar_app": True,
        "host_state": "present",
    }
    assert host.headers["x-litestar-host-middleware"] == "1"
    assert rakit_root.status_code == 200
    assert "D4.1 Litestar proof" in rakit_root.text
    assert rakit_descendant.status_code == 200
    assert rakit_descendant.json() == {"status": "ok"}
    assert false_boundary.status_code == 200
    assert false_boundary.json()["owner"] == "litestar"
    assert "x-litestar-host-middleware" not in rakit_root.headers
    assert all("litestar_app" not in scope for scope in recorded_admin.scopes)
    assert all("litestar.host" not in scope.get("state", {}) for scope in recorded_admin.scopes)


def test_real_litestar_and_rakit_lifecycles_run_once_in_composition_order() -> None:
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
        assert events == ["litestar.startup", "rakit.startup"]

    assert events == [
        "litestar.startup",
        "rakit.startup",
        "rakit.shutdown",
        "litestar.shutdown",
    ]


def test_litestar_startup_failure_does_not_start_rakit() -> None:
    events: list[str] = []
    admin = _build_admin()

    async def rakit_startup() -> None:
        events.append("rakit.startup")

    admin.on_startup(rakit_startup)
    app = _compose(_build_host(events, fail_startup=True), admin)

    with (
        pytest.raises(Exception, match="litestar startup failed"),
        TestClient(cast(Any, app), base_url="http://localhost"),
    ):
        pass

    assert events == ["litestar.startup", "litestar.shutdown"]
    assert admin.lifecycle.state is RuntimeState.CREATED


def test_rakit_startup_failure_rolls_litestar_back() -> None:
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

    assert events == ["litestar.startup", "rakit.startup", "litestar.shutdown"]
    assert admin.lifecycle.state is RuntimeState.FAILED


def test_real_litestar_root_path_forms_preserve_composition_ownership() -> None:
    events: list[str] = []
    admin = _build_admin()
    recorded_admin = _RecordingAdmin(admin)
    app = _compose(_build_host(events), recorded_admin)

    with TestClient(cast(Any, app), base_url="http://localhost", root_path="/proxy") as client:
        host_separate = client.get("/host")
        rakit_separate = client.get("/admin/_system/ready")
        host_included = client.get("/proxy/host")
        rakit_included = client.get("/proxy/admin/_system/ready")
        administrator = client.get("/administrator")
        proxy_two = client.get("/proxy2/admin")

    assert host_separate.json()["owner"] == "litestar"
    assert host_included.json()["owner"] == "litestar"
    assert rakit_separate.json() == {"status": "ready"}
    assert rakit_included.json() == {"status": "ready"}
    assert administrator.json()["owner"] == "litestar"
    assert proxy_two.json()["owner"] == "litestar"
    assert len(recorded_admin.scopes) == 2
    assert all(scope["path"].startswith("/") for scope in recorded_admin.scopes)
    assert all(scope["path"] not in {"/admin", "/proxy/admin"} for scope in recorded_admin.scopes)
    assert all(scope["root_path"] == "/proxy/admin" for scope in recorded_admin.scopes)


def test_litestar_host_exception_and_rakit_response_keep_framework_ownership() -> None:
    events: list[str] = []
    admin = _build_admin()
    app = _compose(_build_host(events), admin)

    with TestClient(cast(Any, app), base_url="http://localhost") as client:
        host_error = client.get("/host-error")
        rakit_error = client.get("/admin/not-a-rakit-route")

    assert host_error.status_code == 418
    assert "litestar-owned" in host_error.text
    assert host_error.headers["x-litestar-host-middleware"] == "1"
    assert rakit_error.status_code == 404
    assert "litestar-owned" not in rakit_error.text
    assert "x-litestar-host-middleware" not in rakit_error.headers


def test_real_litestar_websocket_remains_host_owned() -> None:
    events: list[str] = []
    admin = _build_admin()
    app = _compose(_build_host(events), admin)

    with (
        TestClient(cast(Any, app), base_url="http://localhost") as client,
        client.websocket_connect("/ws") as socket,
    ):
        socket.send_text("ping")
        assert socket.receive_text() == "litestar:ping"
