from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any

import pytest
from rakit import compose_asgi

Scope = dict[str, Any]
Message = dict[str, Any]


@dataclass
class ProbeApp:
    name: str
    body: bytes = b"ok"
    lifespan_state: dict[str, Any] = field(default_factory=dict)
    startup_error: BaseException | None = None
    startup_failed_message: str | None = None
    shutdown_error: BaseException | None = None
    supports_lifespan: bool = True
    events: list[str] = field(default_factory=list)
    scopes: list[Scope] = field(default_factory=list)
    invocations: int = 0

    async def __call__(self, scope, receive, send) -> None:
        self.invocations += 1
        snapshot = dict(scope)
        if isinstance(scope.get("state"), dict):
            snapshot["state"] = dict(scope["state"])
        if isinstance(scope.get("path_params"), dict):
            snapshot["path_params"] = dict(scope["path_params"])
        self.scopes.append(snapshot)

        if scope["type"] == "lifespan":
            if not self.supports_lifespan:
                return
            while True:
                message = await receive()
                if message["type"] == "lifespan.startup":
                    self.events.append(f"{self.name}.startup")
                    if self.startup_error is not None:
                        raise self.startup_error
                    if self.startup_failed_message is not None:
                        await send(
                            {
                                "type": "lifespan.startup.failed",
                                "message": self.startup_failed_message,
                            }
                        )
                        return
                    scope["state"].update(self.lifespan_state)
                    await send({"type": "lifespan.startup.complete"})
                elif message["type"] == "lifespan.shutdown":
                    self.events.append(f"{self.name}.shutdown")
                    if self.shutdown_error is not None:
                        raise self.shutdown_error
                    await send({"type": "lifespan.shutdown.complete"})
                    return
                else:
                    raise AssertionError(f"unexpected lifespan message: {message}")
            return

        if scope["type"] == "http":
            await send({"type": "http.response.start", "status": 200, "headers": []})
            await send({"type": "http.response.body", "body": self.body})
        elif scope["type"] == "websocket":
            self.events.append(f"{self.name}.websocket")


@dataclass
class LifespanSession:
    app: Any
    receive_queue: asyncio.Queue[Message]
    messages: list[Message]
    task: asyncio.Task[None]

    async def shutdown(self) -> None:
        await self.receive_queue.put({"type": "lifespan.shutdown"})
        try:
            await _wait_for_message(self.messages, "lifespan.shutdown.complete")
        except AssertionError:
            if self.task.done():
                self.task.result()
            raise
        await self.task


def _scope(
    scope_type: str,
    path: str = "/",
    *,
    raw_path: bytes | None = None,
    root_path: str = "",
    query_string: bytes = b"",
    state: dict[str, Any] | None = None,
) -> Scope:
    result: Scope = {
        "type": scope_type,
        "asgi": {"version": "3.0", "spec_version": "2.4"},
        "path": path,
        "raw_path": path.encode() if raw_path is None else raw_path,
        "root_path": root_path,
        "query_string": query_string,
        "state": {} if state is None else state,
        "headers": [],
    }
    if scope_type == "http":
        result.update(
            {
                "http_version": "1.1",
                "method": "GET",
                "scheme": "http",
                "client": ("127.0.0.1", 1234),
                "server": ("testserver", 80),
            }
        )
    return result


async def _call(app: Any, scope: Scope) -> list[Message]:
    messages: list[Message] = []
    request_sent = False

    async def receive() -> Message:
        nonlocal request_sent
        if not request_sent:
            request_sent = True
            return {"type": "http.request", "body": b"", "more_body": False}
        return {"type": "http.disconnect"}

    async def send(message: Message) -> None:
        messages.append(dict(message))

    await app(scope, receive, send)
    return messages


async def _wait_for_message(messages: list[Message], message_type: str) -> Message:
    for _ in range(100):
        for message in messages:
            if message["type"] == message_type:
                return message
        await asyncio.sleep(0)
    raise AssertionError(f"did not receive {message_type}: {messages}")


async def _start_lifespan(app: Any, *, state: dict[str, Any] | None = None) -> LifespanSession:
    receive_queue: asyncio.Queue[Message] = asyncio.Queue()
    messages: list[Message] = []

    async def receive() -> Message:
        return await receive_queue.get()

    async def send(message: Message) -> None:
        messages.append(dict(message))

    task = asyncio.create_task(app(_scope("lifespan", state=state), receive, send))
    await receive_queue.put({"type": "lifespan.startup"})
    await _wait_for_message(messages, "lifespan.startup.complete")
    return LifespanSession(app, receive_queue, messages, task)


def _fake_admin(rakit_app: Any) -> Any:
    class FakeAdmin:
        def asgi(self) -> Any:
            return rakit_app

    return FakeAdmin()


@pytest.mark.anyio
async def test_public_composition_routes_host_and_rakit_with_isolated_scopes() -> None:
    host = ProbeApp("host", body=b"host")
    rakit = ProbeApp("rakit", body=b"rakit")
    app = compose_asgi(host, _fake_admin(rakit), path="/admin")

    original = _scope("http", "/admin/products", raw_path=b"/admin/products")
    original["path_params"] = {"unchanged": "yes"}
    original_snapshot = dict(original)
    original_snapshot["state"] = dict(original["state"])
    original_snapshot["path_params"] = dict(original["path_params"])

    await _call(app, original)
    await _call(app, _scope("http", "/api/users"))

    assert rakit.scopes[-1]["path"] == "/products"
    assert host.scopes[-1]["path"] == "/api/users"
    assert original == original_snapshot


@pytest.mark.anyio
async def test_prefix_matching_root_and_boundary() -> None:
    host = ProbeApp("host")
    rakit = ProbeApp("rakit")
    app = compose_asgi(host, _fake_admin(rakit), path="/admin")

    await _call(app, _scope("http", "/admin"))
    await _call(app, _scope("http", "/admin/"))
    await _call(app, _scope("http", "/administrator"))

    assert [scope["path"] for scope in rakit.scopes] == ["/", "/"]
    assert [scope["path"] for scope in host.scopes] == ["/administrator"]


@pytest.mark.anyio
async def test_nested_root_path_query_and_raw_path_are_transformed_consistently() -> None:
    host = ProbeApp("host")
    rakit = ProbeApp("rakit")
    app = compose_asgi(host, _fake_admin(rakit), path="/admin")

    await _call(
        app,
        _scope(
            "http",
            "/admin/search/é",
            raw_path=b"/admin/search/%C3%A9",
            root_path="/proxy",
            query_string=b"q=%C3%A9&keep=1",
        ),
    )

    child = rakit.scopes[-1]
    assert child["root_path"] == "/proxy/admin"
    assert child["path"] == "/search/é"
    assert child["raw_path"] == b"/search/%C3%A9"
    assert child["query_string"] == b"q=%C3%A9&keep=1"

    without_raw_path = _scope("http", "/admin/no-raw")
    without_raw_path.pop("raw_path")
    await _call(app, without_raw_path)
    assert "raw_path" not in rakit.scopes[-1]


@pytest.mark.anyio
async def test_host_websocket_and_unknown_scope_remain_host_owned() -> None:
    host = ProbeApp("host")
    rakit = ProbeApp("rakit")
    app = compose_asgi(host, _fake_admin(rakit), path="/admin")

    await _call(app, _scope("websocket", "/socket"))
    await _call(app, _scope("custom", "/admin/opaque"))

    assert "host.websocket" in host.events
    assert [scope["type"] for scope in host.scopes] == ["websocket", "custom"]
    assert not rakit.scopes


@pytest.mark.anyio
async def test_host_local_middleware_does_not_wrap_rakit_dispatch() -> None:
    host_calls: list[str] = []
    host = ProbeApp("host")
    rakit = ProbeApp("rakit")

    async def host_middleware(scope, receive, send) -> None:
        host_calls.append(scope["path"])
        await host(scope, receive, send)

    app = compose_asgi(host_middleware, _fake_admin(rakit), path="/admin")
    await _call(app, _scope("http", "/admin"))
    assert host_calls == []

    await _call(app, _scope("http", "/host"))
    assert host_calls == ["/host"]


@pytest.mark.anyio
async def test_composed_lifespan_orders_children_once_and_propagates_state() -> None:
    events: list[str] = []
    host = ProbeApp("host", lifespan_state={"host-resource": object()}, events=events)
    rakit = ProbeApp("rakit", lifespan_state={"rakit-resource": object()}, events=events)
    app = compose_asgi(host, _fake_admin(rakit), path="/admin")

    session = await _start_lifespan(app, state={"outer": "preserved"})
    assert events == ["host.startup", "rakit.startup"]
    assert session.messages == [{"type": "lifespan.startup.complete"}]
    assert host.scopes[0]["state"]["outer"] == "preserved"
    assert rakit.scopes[0]["state"]["outer"] == "preserved"

    await _call(app, _scope("http", "/api", state={"request": "host"}))
    await _call(app, _scope("http", "/admin", state={"request": "rakit"}))

    assert host.scopes[-1]["state"]["host-resource"] is host.lifespan_state["host-resource"]
    assert "rakit-resource" not in host.scopes[-1]["state"]
    assert rakit.scopes[-1]["state"]["rakit-resource"] is rakit.lifespan_state["rakit-resource"]
    assert "host-resource" not in rakit.scopes[-1]["state"]

    await session.shutdown()
    assert events == ["host.startup", "rakit.startup", "rakit.shutdown", "host.shutdown"]
    assert host.invocations == 2
    assert rakit.invocations == 2


@pytest.mark.anyio
async def test_host_startup_failure_prevents_rakit_startup() -> None:
    host = ProbeApp("host", startup_failed_message="host unavailable")
    rakit = ProbeApp("rakit")
    app = compose_asgi(host, _fake_admin(rakit), path="/admin")

    receive_queue: asyncio.Queue[Message] = asyncio.Queue()
    messages: list[Message] = []

    async def receive() -> Message:
        return await receive_queue.get()

    async def send(message: Message) -> None:
        messages.append(dict(message))

    task = asyncio.create_task(app(_scope("lifespan"), receive, send))
    await receive_queue.put({"type": "lifespan.startup"})
    failed = await _wait_for_message(messages, "lifespan.startup.failed")
    with pytest.raises(RuntimeError):
        await task

    assert "host unavailable" in failed["message"]
    assert rakit.events == []


@pytest.mark.anyio
async def test_rakit_startup_failure_rolls_host_back_and_never_ready() -> None:
    events: list[str] = []
    host = ProbeApp("host", events=events)
    rakit = ProbeApp("rakit", startup_failed_message="rakit unavailable", events=events)
    app = compose_asgi(host, _fake_admin(rakit), path="/admin")

    receive_queue: asyncio.Queue[Message] = asyncio.Queue()
    messages: list[Message] = []

    async def receive() -> Message:
        return await receive_queue.get()

    async def send(message: Message) -> None:
        messages.append(dict(message))

    task = asyncio.create_task(app(_scope("lifespan"), receive, send))
    await receive_queue.put({"type": "lifespan.startup"})
    failed = await _wait_for_message(messages, "lifespan.startup.failed")
    with pytest.raises(RuntimeError):
        await task

    assert "rakit unavailable" in failed["message"]
    assert events == ["host.startup", "rakit.startup", "host.shutdown"]
    assert {message["type"] for message in messages} == {"lifespan.startup.failed"}


@pytest.mark.anyio
async def test_child_exception_after_accepting_startup_is_not_unsupported() -> None:
    host = ProbeApp("host", startup_error=RuntimeError("accepted startup failure"))
    rakit = ProbeApp("rakit")
    app = compose_asgi(host, _fake_admin(rakit), path="/admin")

    receive_queue: asyncio.Queue[Message] = asyncio.Queue()
    messages: list[Message] = []

    async def receive() -> Message:
        return await receive_queue.get()

    async def send(message: Message) -> None:
        messages.append(dict(message))

    task = asyncio.create_task(app(_scope("lifespan"), receive, send))
    await receive_queue.put({"type": "lifespan.startup"})
    failed = await _wait_for_message(messages, "lifespan.startup.failed")
    with pytest.raises(RuntimeError, match="accepted startup failure"):
        await task

    assert "accepted startup failure" in failed["message"]
    assert not rakit.events


@pytest.mark.anyio
async def test_shutdown_failure_still_stops_host_and_preserves_failure() -> None:
    events: list[str] = []
    host = ProbeApp("host", events=events)
    rakit = ProbeApp("rakit", shutdown_error=RuntimeError("rakit cleanup"), events=events)
    app = compose_asgi(host, _fake_admin(rakit), path="/admin")
    session = await _start_lifespan(app)

    await session.receive_queue.put({"type": "lifespan.shutdown"})
    failed = await _wait_for_message(session.messages, "lifespan.shutdown.failed")
    with pytest.raises(RuntimeError):
        await session.task

    assert "rakit.shutdown" in events
    assert "host.shutdown" in events
    assert "rakit cleanup" in failed["message"]


@pytest.mark.anyio
async def test_multiple_shutdown_failures_are_all_reported_after_cleanup_attempts() -> None:
    events: list[str] = []
    host = ProbeApp("host", shutdown_error=RuntimeError("host cleanup"), events=events)
    rakit = ProbeApp("rakit", shutdown_error=RuntimeError("rakit cleanup"), events=events)
    app = compose_asgi(host, _fake_admin(rakit), path="/admin")
    session = await _start_lifespan(app)

    await session.receive_queue.put({"type": "lifespan.shutdown"})
    failed = await _wait_for_message(session.messages, "lifespan.shutdown.failed")
    with pytest.raises(ExceptionGroup) as shutdown_error:
        await session.task

    assert events == ["host.startup", "rakit.startup", "rakit.shutdown", "host.shutdown"]
    assert "rakit cleanup" in failed["message"]
    assert "host cleanup" in failed["message"]
    assert {str(error) for error in shutdown_error.value.exceptions} == {
        "rakit cleanup",
        "host cleanup",
    }


@pytest.mark.anyio
async def test_unsupported_child_lifespan_does_not_block_other_child() -> None:
    host = ProbeApp("host", supports_lifespan=False)
    rakit = ProbeApp("rakit")
    app = compose_asgi(host, _fake_admin(rakit), path="/admin")

    session = await _start_lifespan(app)
    assert rakit.events == ["rakit.startup"]
    await session.shutdown()
    assert rakit.events == ["rakit.startup", "rakit.shutdown"]
    assert host.scopes[0]["type"] == "lifespan"


@pytest.mark.anyio
async def test_raw_path_mismatch_fails_explicitly() -> None:
    host = ProbeApp("host")
    rakit = ProbeApp("rakit")
    app = compose_asgi(host, _fake_admin(rakit), path="/admin")

    with pytest.raises(ValueError, match="raw_path"):
        await _call(app, _scope("http", "/admin/products", raw_path=b"/wrong/products"))


def test_invalid_composition_prefix_is_rejected() -> None:
    host = ProbeApp("host")
    rakit = ProbeApp("rakit")

    with pytest.raises(ValueError, match="path"):
        compose_asgi(host, _fake_admin(rakit), path="admin")
    with pytest.raises(ValueError, match="query"):
        compose_asgi(host, _fake_admin(rakit), path="/admin?x=1")
