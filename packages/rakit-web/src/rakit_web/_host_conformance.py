"""Internal D4 host conformance model.

The model deliberately accepts a host composer instead of importing any host
framework. D4.1+ can reuse it with real framework applications while keeping
the Rakit application factory framework-neutral.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import anyio
from starlette.types import ASGIApp, Message, Receive, Scope, Send


@dataclass(frozen=True, slots=True)
class ASGIHostConformanceCase:
    name: str
    build_admin: Callable[[], object]
    compose: Callable[[ASGIApp, object], ASGIApp]


@dataclass(frozen=True, slots=True)
class ASGIHostConformanceResult:
    case_name: str
    lifecycle_events: tuple[str, ...]
    host_status: int
    rakit_status: int


def _scope(scope_type: str, path: str, state: dict[str, Any] | None = None) -> Scope:
    return {
        "type": scope_type,
        "asgi": {"version": "3.0", "spec_version": "2.4"},
        "http_version": "1.1",
        "method": "GET",
        "scheme": "http",
        "path": path,
        "raw_path": path.encode("ascii"),
        "query_string": b"",
        "root_path": "",
        "headers": [],
        "client": ("127.0.0.1", 1234),
        "server": ("testserver", 80),
        "state": {} if state is None else state,
    }


async def _request(app: ASGIApp, scope: Scope) -> tuple[dict[str, Any], ...]:
    sent: list[dict[str, Any]] = []
    request_sent = False

    async def receive() -> Message:
        nonlocal request_sent
        if not request_sent:
            request_sent = True
            return {"type": "http.request", "body": b"", "more_body": False}
        return {"type": "http.disconnect"}

    async def send(message: Message) -> None:
        sent.append(dict(message))

    await app(scope, receive, send)
    return tuple(sent)


class _ProbeHost:
    def __init__(self, events: list[str]) -> None:
        self.events = events
        self.scope_states: list[dict[str, Any]] = []

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "lifespan":
            message = await receive()
            assert message["type"] == "lifespan.startup"
            self.events.append("host.startup")
            scope["state"]["conformance.host"] = True
            await send({"type": "lifespan.startup.complete"})
            message = await receive()
            assert message["type"] == "lifespan.shutdown"
            self.events.append("host.shutdown")
            await send({"type": "lifespan.shutdown.complete"})
            return

        self.scope_states.append(dict(scope["state"]))
        assert scope["path"] == "/host"
        assert "conformance.rakit" not in scope["state"]
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"host"})


def _status(messages: tuple[dict[str, Any], ...]) -> int:
    starts = [message for message in messages if message.get("type") == "http.response.start"]
    if len(starts) != 1:
        raise AssertionError(f"expected one HTTP response start, got {starts}")
    return int(starts[0]["status"])


async def run_host_conformance(case: ASGIHostConformanceCase) -> ASGIHostConformanceResult:
    """Run the shared D4 contract against a case-supplied host composer."""

    events: list[str] = []
    host = _ProbeHost(events)
    admin = case.build_admin()
    register_startup = getattr(admin, "on_startup", None)
    if callable(register_startup):

        async def record_rakit_startup() -> None:
            events.append("rakit.startup")

        register_startup(record_rakit_startup)
    register_shutdown = getattr(admin, "on_shutdown", None)
    if callable(register_shutdown):

        async def record_rakit_shutdown() -> None:
            events.append("rakit.shutdown")

        register_shutdown(record_rakit_shutdown)
    app = case.compose(host, admin)

    input_send, input_receive = anyio.create_memory_object_stream[Message](4)
    output_send, output_receive = anyio.create_memory_object_stream[Message](4)
    finished = anyio.Event()
    lifecycle_scope = _scope("lifespan", "/", {"outer": "preserved"})

    async def receive() -> Message:
        return await input_receive.receive()

    async def send(message: Message) -> None:
        await output_send.send(dict(message))

    async def run_app() -> None:
        try:
            await app(lifecycle_scope, receive, send)
        finally:
            finished.set()

    async with anyio.create_task_group() as task_group:
        task_group.start_soon(run_app)
        await input_send.send({"type": "lifespan.startup"})
        startup = await output_receive.receive()
        if startup.get("type") != "lifespan.startup.complete":
            raise AssertionError(f"{case.name}: composition did not start: {startup}")

        host_messages = await _request(app, _scope("http", "/host"))
        rakit_messages = await _request(app, _scope("http", "/admin"))

        await input_send.send({"type": "lifespan.shutdown"})
        shutdown = await output_receive.receive()
        if shutdown.get("type") != "lifespan.shutdown.complete":
            raise AssertionError(f"{case.name}: composition did not stop: {shutdown}")
        with anyio.CancelScope(shield=True):
            await finished.wait()

    return ASGIHostConformanceResult(
        case_name=case.name,
        lifecycle_events=tuple(events),
        host_status=_status(host_messages),
        rakit_status=_status(rakit_messages),
    )


__all__ = ["ASGIHostConformanceCase", "ASGIHostConformanceResult", "run_host_conformance"]
