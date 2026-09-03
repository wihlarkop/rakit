"""Protocol-level composition for a host ASGI app and a Rakit Admin app."""

from __future__ import annotations

from collections.abc import Mapping
from contextlib import suppress
from dataclasses import dataclass
from typing import Any, Literal
from urllib.parse import unquote_to_bytes

import anyio
from anyio.abc import TaskGroup
from starlette.types import ASGIApp, Message, Receive, Scope, Send

_ChildStatus = Literal["not-started", "unsupported", "started", "stopped"]
_ChildEvent = tuple[str, Any]
_LifecycleStatus = Literal["unmanaged", "starting", "ready", "stopping", "failed", "stopped"]
_NOT_READY_BODY = b"Application is not ready"


def _validate_prefix(path: str) -> str:
    if not isinstance(path, str) or not path:
        raise ValueError("ASGI composition path must be a non-empty absolute path")
    if not path.startswith("/"):
        raise ValueError("ASGI composition path must be an absolute path")
    if "?" in path or "#" in path:
        raise ValueError("ASGI composition path must not contain a query or fragment")
    if "\x00" in path:
        raise ValueError("ASGI composition path must not contain a null character")
    normalized = path.rstrip("/")
    return normalized or "/"


def _copy_scope(scope: Scope) -> Scope:
    copied = dict(scope)
    for key in ("state", "path_params"):
        value = scope.get(key)
        if value is not None:
            if not isinstance(value, Mapping):
                raise TypeError(f"ASGI scope {key!r} must be a mapping when present")
            copied[key] = dict(value)
    return copied


def _scope_state(scope: Scope) -> dict[str, Any]:
    value = scope.get("state")
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise TypeError("ASGI scope state must be a mapping when present")
    return dict(value)


def _join_root_path(root_path: str, prefix: str) -> str:
    if not isinstance(root_path, str):
        raise TypeError("ASGI scope root_path must be a string")
    if prefix == "/":
        return root_path
    if not root_path or root_path == "/":
        return prefix
    return root_path.rstrip("/") + prefix


def _normalized_route_path(path: str, root_path: str) -> str:
    """Normalize server-specific inclusion of ``root_path`` in ``path``."""

    if not isinstance(path, str) or not path.startswith("/"):
        raise ValueError("ASGI HTTP/WebSocket scope must contain an absolute path")
    if not isinstance(root_path, str):
        raise TypeError("ASGI scope root_path must be a string")
    root = root_path.rstrip("/")
    if not root or root == "/":
        return path
    if path == root:
        return "/"
    if path.startswith(root + "/"):
        return path[len(root) :]
    return path


def _decoded_raw_path(raw_path: bytes) -> str:
    try:
        return unquote_to_bytes(raw_path).decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError("ASGI raw_path is not valid UTF-8 after percent decoding") from exc


def _raw_prefix_end(raw_path: bytes, prefix: str) -> int:
    """Find the raw byte boundary for a decoded UTF-8 prefix.

    Scanning percent triplets instead of decoding and re-encoding preserves the
    caller's raw suffix representation (for example, ``%C3%A9`` remains
    ``%C3%A9``).
    """

    target = prefix.encode("utf-8")
    decoded_prefix = bytearray()
    raw_index = 0
    while len(decoded_prefix) < len(target):
        if raw_index >= len(raw_path):
            raise ValueError("ASGI raw_path ends before the mounted prefix")
        if raw_path[raw_index : raw_index + 1] == b"%":
            triplet = raw_path[raw_index : raw_index + 3]
            if len(triplet) != 3 or any(
                char not in b"0123456789abcdefABCDEF" for char in triplet[1:]
            ):
                step = 1
                decoded_prefix.extend(raw_path[raw_index : raw_index + 1])
            else:
                step = 3
                decoded_prefix.append(int(triplet[1:3], 16))
        else:
            step = 1
            decoded_prefix.extend(raw_path[raw_index : raw_index + 1])
        raw_index += step
    if bytes(decoded_prefix) != target:
        raise ValueError("ASGI raw_path cannot represent the mounted prefix boundary")
    return raw_index


def _transform_rakit_scope(scope: Scope, prefix: str, route_path: str) -> Scope:
    path = scope.get("path")
    if not isinstance(path, str) or not path.startswith("/"):
        raise ValueError("ASGI HTTP/WebSocket scope must contain an absolute path")

    copied = _copy_scope(scope)
    if prefix == "/":
        child_path = route_path
    elif route_path == prefix or route_path == prefix + "/":
        child_path = "/"
    else:
        child_path = route_path[len(prefix) :]
        if not child_path.startswith("/"):
            raise ValueError("ASGI mounted path transformation crossed a segment boundary")

    copied["path"] = child_path
    root_path = scope.get("root_path", "")
    copied["root_path"] = _join_root_path(root_path, prefix)

    if "raw_path" in scope and scope["raw_path"] is not None:
        raw_path = scope["raw_path"]
        if not isinstance(raw_path, bytes):
            raise TypeError("ASGI raw_path must be bytes when present")
        if _decoded_raw_path(raw_path) != path:
            raise ValueError("ASGI raw_path is inconsistent with scope path")

        normalized_raw_path = raw_path
        normalized_root = root_path.rstrip("/")
        if (
            normalized_root
            and normalized_root != "/"
            and (path == normalized_root or path.startswith(normalized_root + "/"))
        ):
            raw_root_end = _raw_prefix_end(raw_path, normalized_root)
            normalized_raw_path = raw_path[raw_root_end:] or b"/"
            if _decoded_raw_path(normalized_raw_path) != route_path:
                raise ValueError("ASGI raw_path is inconsistent with normalized scope path")

        if prefix == "/":
            child_raw_path = normalized_raw_path
        else:
            raw_end = _raw_prefix_end(normalized_raw_path, prefix)
            child_raw_path = normalized_raw_path[raw_end:]
            if not child_raw_path:
                child_raw_path = b"/"
            if _decoded_raw_path(child_raw_path) != child_path:
                raise ValueError("ASGI raw_path is inconsistent with transformed scope path")
        copied["raw_path"] = child_raw_path

    return copied


def _request_scope(scope: Scope, lifespan_state: Mapping[str, Any]) -> Scope:
    copied = _copy_scope(scope)
    if copied.get("state") is not None:
        state = _scope_state(copied)
        state.update(lifespan_state)
        copied["state"] = state
    return copied


def _is_cancelled(error: BaseException) -> bool:
    return isinstance(error, anyio.get_cancelled_exc_class())


def _combine_failures(message: str, failures: list[BaseException]) -> BaseException:
    if len(failures) == 1:
        return failures[0]
    if all(isinstance(error, Exception) for error in failures):
        return ExceptionGroup(
            message, [error for error in failures if isinstance(error, Exception)]
        )
    return BaseExceptionGroup(message, failures)


def _failure_message(error: BaseException) -> str:
    if isinstance(error, BaseExceptionGroup):
        details = "; ".join(_failure_message(child) for child in error.exceptions)
        return f"{error.args[0]}: {details}"
    return str(error)


class _ChildLifespanError(RuntimeError):
    def __init__(self, child_name: str, phase: str, detail: str) -> None:
        super().__init__(f"{child_name} lifespan {phase} failed: {detail}")
        self.child_name = child_name
        self.phase = phase


@dataclass
class _ChildLifespan:
    name: str
    app: ASGIApp
    parent_scope: Scope
    status: _ChildStatus = "not-started"

    def __post_init__(self) -> None:
        self._input_send: Any = None
        self._events_send: Any = None
        self._events: Any = None
        self._scope: Scope | None = None
        self._cancel_scope: anyio.CancelScope | None = None
        self._finished: anyio.Event | None = None
        self._startup_accepted = False
        self.state: dict[str, Any] = {}

    async def _run(self, receive: Any, events_send: Any) -> None:
        async def child_receive() -> Message:
            message = await receive.receive()
            if message.get("type") == "lifespan.startup":
                self._startup_accepted = True
            return message

        async def child_send(message: Message) -> None:
            await events_send.send(("message", dict(message)))

        with anyio.CancelScope() as cancel_scope:
            self._cancel_scope = cancel_scope
            try:
                assert self._scope is not None
                await self.app(self._scope, child_receive, child_send)
            except BaseException as error:
                with suppress(BaseException):
                    await events_send.send(("error", error))
            else:
                await events_send.send(("returned", None))
            finally:
                self._cancel_scope = None
                assert self._finished is not None
                self._finished.set()

    async def _open(self, task_group: TaskGroup) -> None:
        input_send, input_receive = anyio.create_memory_object_stream[Message](4)
        events_send, events_receive = anyio.create_memory_object_stream[_ChildEvent](8)
        self._input_send = input_send
        self._events_send = events_send
        self._events = events_receive
        self._finished = anyio.Event()
        self._scope = _copy_scope(self.parent_scope)
        task_group.start_soon(self._run, input_receive, events_send)

    async def _close(self, *, cancel: bool) -> None:
        cancel_scope = self._cancel_scope
        input_send, events_send, events = self._input_send, self._events_send, self._events
        self._input_send = None
        self._events_send = None
        self._events = None
        if cancel and cancel_scope is not None:
            cancel_scope.cancel()
        with anyio.CancelScope(shield=True):
            if self._finished is not None:
                await self._finished.wait()
            if input_send is not None:
                await input_send.aclose()
            if events_send is not None:
                await events_send.aclose()
            if events is not None:
                await events.aclose()

    async def _next_event(self) -> _ChildEvent:
        if self._events is None:
            raise RuntimeError(f"{self.name} lifespan controller is closed")
        return await self._events.receive()

    async def start(self, task_group: TaskGroup) -> None:
        await self._open(task_group)
        assert self._input_send is not None
        await self._input_send.send({"type": "lifespan.startup"})
        try:
            while True:
                event_type, payload = await self._next_event()
                if event_type == "returned":
                    await self._close(cancel=False)
                    if not self._startup_accepted:
                        self.status = "unsupported"
                        return
                    raise _ChildLifespanError(
                        self.name, "startup", "application returned before startup completed"
                    )
                if event_type == "error":
                    await self._close(cancel=False)
                    error = payload
                    if _is_cancelled(error):
                        raise error
                    if not self._startup_accepted:
                        self.status = "unsupported"
                        return
                    raise error

                message_type = payload.get("type")
                if message_type == "lifespan.startup.complete":
                    assert self._scope is not None
                    self.state = _scope_state(self._scope)
                    self.status = "started"
                    return
                if message_type == "lifespan.startup.failed":
                    detail = str(payload.get("message", "child reported startup failure"))
                    await self._close(cancel=True)
                    raise _ChildLifespanError(self.name, "startup", detail)
                raise _ChildLifespanError(
                    self.name,
                    "startup",
                    f"unexpected message {message_type!r}",
                )
        except BaseException:
            if self._events is not None:
                await self._close(cancel=True)
            raise

    async def stop(self) -> None:
        if self.status != "started":
            return
        assert self._input_send is not None
        await self._input_send.send({"type": "lifespan.shutdown"})
        try:
            while True:
                event_type, payload = await self._next_event()
                if event_type == "returned":
                    raise _ChildLifespanError(
                        self.name, "shutdown", "application returned before shutdown completed"
                    )
                if event_type == "error":
                    error = payload
                    if _is_cancelled(error):
                        raise error
                    raise error

                message_type = payload.get("type")
                if message_type == "lifespan.shutdown.complete":
                    self.status = "stopped"
                    await self._close(cancel=False)
                    return
                if message_type == "lifespan.shutdown.failed":
                    detail = str(payload.get("message", "child reported shutdown failure"))
                    await self._close(cancel=True)
                    raise _ChildLifespanError(self.name, "shutdown", detail)
                raise _ChildLifespanError(
                    self.name,
                    "shutdown",
                    f"unexpected message {message_type!r}",
                )
        except BaseException:
            if self._events is not None:
                await self._close(cancel=True)
            raise


class _ASGIComposition:
    def __init__(self, host: ASGIApp, rakit: ASGIApp, prefix: str) -> None:
        self._host = host
        self._rakit = rakit
        self._prefix = prefix
        self._host_state: dict[str, Any] = {}
        self._rakit_state: dict[str, Any] = {}
        self._lifecycle_status: _LifecycleStatus = "unmanaged"
        self._readiness_event: anyio.Event | None = None

    def _matches_rakit(self, path: str) -> bool:
        return self._prefix == "/" or path == self._prefix or path.startswith(self._prefix + "/")

    async def _stop_children(self, *children: _ChildLifespan) -> list[BaseException]:
        failures: list[BaseException] = []
        cancellation: BaseException | None = None
        for child in children:
            try:
                await child.stop()
            except BaseException as error:
                if _is_cancelled(error):
                    cancellation = cancellation or error
                else:
                    failures.append(error)
        if cancellation is not None:
            if failures:
                raise BaseExceptionGroup(
                    "ASGI child shutdown cancellation and failures",
                    [cancellation, *failures],
                )
            raise cancellation
        return failures

    async def _send_failure(
        self, send: Send, phase: Literal["startup", "shutdown"], error: BaseException
    ) -> None:
        await send(
            {
                "type": f"lifespan.{phase}.failed",
                "message": _failure_message(error),
            }
        )

    async def _lifespan_with_group(
        self,
        scope: Scope,
        receive: Receive,
        send: Send,
        task_group: TaskGroup,
    ) -> None:
        host_lifespan = _ChildLifespan("host", self._host, scope)
        rakit_lifespan = _ChildLifespan("rakit", self._rakit, scope)
        host_started = False
        rakit_started = False

        try:
            startup_message = await receive()
            if startup_message.get("type") != "lifespan.startup":
                raise RuntimeError(
                    f"unexpected root lifespan message {startup_message.get('type')!r}"
                )
            try:
                await host_lifespan.start(task_group)
                host_started = host_lifespan.status == "started"
            except BaseException as error:
                if _is_cancelled(error):
                    raise
                await self._send_failure(send, "startup", error)
                raise

            try:
                await rakit_lifespan.start(task_group)
                rakit_started = rakit_lifespan.status == "started"
            except BaseException as error:
                if _is_cancelled(error):
                    with anyio.CancelScope(shield=True):
                        rollback_failures = await self._stop_children(
                            *(
                                child
                                for child, started in (
                                    (rakit_lifespan, rakit_started),
                                    (host_lifespan, host_started),
                                )
                                if started
                            ),
                        )
                    if rollback_failures:
                        raise BaseExceptionGroup(
                            "ASGI startup cancellation cleanup failed",
                            [error, *rollback_failures],
                        ) from None
                    raise
                rollback_failures = []
                if host_started:
                    rollback_failures = await self._stop_children(host_lifespan)
                combined = _combine_failures("ASGI startup failed", [error, *rollback_failures])
                await self._send_failure(send, "startup", combined)
                raise combined from None

            self._host_state = dict(host_lifespan.state)
            self._rakit_state = dict(rakit_lifespan.state)
            try:
                await send({"type": "lifespan.startup.complete"})
                self._lifecycle_status = "ready"
                if self._readiness_event is not None:
                    self._readiness_event.set()
                message = await receive()
                if message.get("type") != "lifespan.shutdown":
                    raise RuntimeError(f"unexpected root lifespan message {message.get('type')!r}")
                self._lifecycle_status = "stopping"
            except BaseException as error:
                if self._lifecycle_status == "ready":
                    self._lifecycle_status = "stopping"
                cleanup_failures: list[BaseException] = []
                cleanup_error: BaseException | None = None
                with anyio.CancelScope(shield=True):
                    try:
                        cleanup_failures = await self._stop_children(rakit_lifespan, host_lifespan)
                    except BaseException as caught_cleanup_error:
                        cleanup_error = caught_cleanup_error
                cleanup_errors = [*cleanup_failures]
                if cleanup_error is not None:
                    cleanup_errors.append(cleanup_error)
                if _is_cancelled(error):
                    if cleanup_errors:
                        raise BaseExceptionGroup(
                            "ASGI root cancellation cleanup failed",
                            [error, *cleanup_errors],
                        ) from None
                    raise
                if cleanup_errors:
                    raise _combine_failures(
                        "ASGI shutdown cleanup failed", [error, *cleanup_errors]
                    ) from None
                raise

            with anyio.CancelScope(shield=True):
                shutdown_failures = await self._stop_children(rakit_lifespan, host_lifespan)
            if shutdown_failures:
                combined = _combine_failures("ASGI shutdown failed", shutdown_failures)
                await self._send_failure(send, "shutdown", combined)
                raise combined
            await send({"type": "lifespan.shutdown.complete"})
        finally:
            self._host_state = {}
            self._rakit_state = {}

    async def _lifespan(self, scope: Scope, receive: Receive, send: Send) -> None:
        if self._lifecycle_status in {"starting", "ready", "stopping"}:
            raise RuntimeError("ASGI composition supports one root lifespan at a time")
        self._lifecycle_status = "starting"
        readiness_event = anyio.Event()
        self._readiness_event = readiness_event
        error: BaseException | None = None
        try:
            async with anyio.create_task_group() as task_group:
                try:
                    await self._lifespan_with_group(scope, receive, send, task_group)
                except BaseException as caught:
                    error = caught
        finally:
            if self._lifecycle_status == "starting":
                self._lifecycle_status = "failed"
            elif self._lifecycle_status == "stopping":
                self._lifecycle_status = "stopped"
            readiness_event.set()
            self._readiness_event = None
        if error is not None:
            raise error

    async def _request_is_ready(self) -> bool:
        if self._lifecycle_status == "starting" and self._readiness_event is not None:
            await self._readiness_event.wait()
        return self._lifecycle_status in {"unmanaged", "ready"}

    async def _send_not_ready(self, scope_type: str, send: Send) -> None:
        if scope_type == "http":
            await send(
                {
                    "type": "http.response.start",
                    "status": 503,
                    "headers": [(b"content-type", b"text/plain; charset=utf-8")],
                }
            )
            await send(
                {
                    "type": "http.response.body",
                    "body": _NOT_READY_BODY,
                }
            )
            return
        await send({"type": "websocket.close", "code": 1013})

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        scope_type = scope.get("type")
        if scope_type == "lifespan":
            await self._lifespan(scope, receive, send)
            return

        if scope_type in {"http", "websocket"}:
            if not await self._request_is_ready():
                await self._send_not_ready(scope_type, send)
                return
            path = scope.get("path")
            if not isinstance(path, str):
                raise ValueError("ASGI HTTP/WebSocket scope must contain a path")
            route_path = _normalized_route_path(path, scope.get("root_path", ""))
            if self._matches_rakit(route_path):
                child_scope = _transform_rakit_scope(scope, self._prefix, route_path)
                if scope.get("state") is not None:
                    child_scope["state"] = _scope_state(scope)
                    child_scope["state"].update(self._rakit_state)
                await self._rakit(child_scope, receive, send)
            else:
                await self._host(_request_scope(scope, self._host_state), receive, send)
            return

        await self._host(_request_scope(scope, self._host_state), receive, send)


def compose_asgi(host: ASGIApp, admin: Any, *, path: str = "/admin") -> ASGIApp:
    """Compose a host ASGI app with an Admin-owned Rakit ASGI runtime.

    The returned application is the single lifespan owner for both children.
    ``admin.asgi()`` is called once during composition, and host framework
    imports are intentionally absent from this protocol-level boundary.
    """

    if not callable(host):
        raise TypeError("ASGI composition host must be callable")
    admin_asgi = getattr(admin, "asgi", None)
    if not callable(admin_asgi):
        raise TypeError("ASGI composition admin must expose a callable asgi()")
    prefix = _validate_prefix(path)
    rakit = admin_asgi()
    if not callable(rakit):
        raise TypeError("Admin.asgi() must return an ASGI callable")
    return _ASGIComposition(host, rakit, prefix)


__all__ = ["compose_asgi"]
