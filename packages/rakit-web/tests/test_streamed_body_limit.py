from collections.abc import Awaitable, Callable

import pytest
from rakit_web.security.middleware import SecurityMiddleware
from starlette.types import Message, Receive, Scope, Send


def _scope(*, headers: list[tuple[bytes, bytes]] | None = None) -> Scope:
    return {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": "/upload",
        "raw_path": b"/upload",
        "query_string": b"",
        "headers": [(b"host", b"localhost"), *(headers or [])],
        "client": ("127.0.0.1", 12345),
        "server": ("localhost", 80),
    }


async def _run(
    app: Callable[[Scope, Receive, Send], Awaitable[None]],
    messages: list[Message],
    *,
    headers: list[tuple[bytes, bytes]] | None = None,
) -> list[Message]:
    incoming = iter(messages)
    sent: list[Message] = []

    async def receive() -> Message:
        return next(incoming)

    async def send(message: Message) -> None:
        sent.append(message)

    middleware = SecurityMiddleware(
        app,
        allowed_hosts=("localhost",),
        content_security_policy_enabled=True,
        max_body_size=10,
    )
    await middleware(_scope(headers=headers), receive, send)
    return sent


async def _consume_body(scope: Scope, receive: Receive, send: Send) -> None:
    while True:
        message = await receive()
        if message["type"] == "http.disconnect":
            return
        if not message.get("more_body", False):
            break
    await send({"type": "http.response.start", "status": 200, "headers": []})
    await send({"type": "http.response.body", "body": b"ok"})


@pytest.mark.parametrize(
    "headers",
    [
        [],
        [(b"content-length", b"5")],
    ],
)
async def test_actual_streamed_bytes_over_limit_return_413(
    headers: list[tuple[bytes, bytes]],
) -> None:
    sent = await _run(
        _consume_body,
        [
            {"type": "http.request", "body": b"123456", "more_body": True},
            {"type": "http.request", "body": b"789012", "more_body": False},
        ],
        headers=headers,
    )
    starts = [message for message in sent if message["type"] == "http.response.start"]
    assert [message["status"] for message in starts] == [413]
    response_headers = dict(starts[0]["headers"])
    assert response_headers[b"x-content-type-options"] == b"nosniff"
    assert b"content-security-policy" in response_headers


async def test_multiple_chunks_at_limit_reach_downstream() -> None:
    sent = await _run(
        _consume_body,
        [
            {"type": "http.request", "body": b"1234", "more_body": True},
            {"type": "http.request", "body": b"567890", "more_body": False},
        ],
    )
    assert (
        next(message for message in sent if message["type"] == "http.response.start")["status"]
        == 200
    )


@pytest.mark.parametrize(
    "headers",
    [
        [(b"content-length", b"nope")],
        [(b"content-length", b"-1")],
        [(b"content-length", b"5"), (b"content-length", b"5")],
        [(b"content-length", b"5"), (b"content-length", b"6")],
        [(b"content-length", b"9" * 5000)],
    ],
)
async def test_invalid_or_duplicate_content_length_fails_before_downstream(
    headers: list[tuple[bytes, bytes]],
) -> None:
    called = False

    async def app(scope: Scope, receive: Receive, send: Send) -> None:
        nonlocal called
        called = True

    sent = await _run(app, [], headers=headers)
    assert called is False
    assert (
        next(message for message in sent if message["type"] == "http.response.start")["status"]
        == 413
    )


async def test_limit_crossing_prevents_post_body_credential_processing() -> None:
    credentials_processed = False

    async def app(scope: Scope, receive: Receive, send: Send) -> None:
        nonlocal credentials_processed
        await receive()
        await receive()
        credentials_processed = True

    sent = await _run(
        app,
        [
            {"type": "http.request", "body": b"123456", "more_body": True},
            {"type": "http.request", "body": b"789012", "more_body": False},
        ],
    )
    assert credentials_processed is False
    assert (
        next(message for message in sent if message["type"] == "http.response.start")["status"]
        == 413
    )


async def test_client_disconnect_passes_through_without_a_response() -> None:
    saw_disconnect = False

    async def app(scope: Scope, receive: Receive, send: Send) -> None:
        nonlocal saw_disconnect
        saw_disconnect = (await receive())["type"] == "http.disconnect"

    sent = await _run(app, [{"type": "http.disconnect"}])
    assert saw_disconnect is True
    assert sent == []


async def test_no_second_response_when_body_limit_crosses_after_start() -> None:
    async def app(scope: Scope, receive: Receive, send: Send) -> None:
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await receive()

    sent = await _run(
        app,
        [{"type": "http.request", "body": b"12345678901", "more_body": False}],
    )
    starts = [message for message in sent if message["type"] == "http.response.start"]
    assert [message["status"] for message in starts] == [200]
