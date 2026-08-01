from collections.abc import Awaitable, Callable

import pytest
from rakit_web.security.middleware import SecurityMiddleware
from starlette.types import Message, Receive, Scope, Send


async def _run(headers: list[tuple[bytes, bytes]]) -> list[Message]:
    called = False
    sent: list[Message] = []

    async def app(scope: Scope, receive: Receive, send: Send) -> None:
        nonlocal called
        called = True
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})

    async def receive() -> Message:
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message: Message) -> None:
        sent.append(message)

    middleware: Callable[[Scope, Receive, Send], Awaitable[None]] = SecurityMiddleware(
        app,
        allowed_hosts=("localhost",),
        content_security_policy_enabled=True,
        max_body_size=1024,
    )
    scope: Scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": "/submit",
        "raw_path": b"/submit",
        "query_string": b"",
        "headers": headers,
        "client": ("127.0.0.1", 12345),
        "server": ("localhost", 80),
    }
    await middleware(scope, receive, send)
    status = next(message["status"] for message in sent if message["type"] == "http.response.start")
    if status != 200:
        assert called is False
    return sent


def _status(messages: list[Message]) -> int:
    return next(
        message["status"] for message in messages if message["type"] == "http.response.start"
    )


def _headers(messages: list[Message]) -> dict[bytes, bytes]:
    start = next(message for message in messages if message["type"] == "http.response.start")
    return dict(start["headers"])


@pytest.mark.parametrize(
    ("headers", "expected_status"),
    [
        ([], 400),
        ([(b"host", b"localhost"), (b"Host", b"localhost")], 400),
        ([(b"host", b"localhost"), (b"HOST", b"evil.example")], 400),
        (
            [
                (b"host", b"localhost"),
                (b"origin", b"http://localhost"),
                (b"Origin", b"http://localhost"),
            ],
            403,
        ),
        (
            [
                (b"host", b"localhost"),
                (b"origin", b"http://localhost"),
                (b"ORIGIN", b"http://evil.example"),
            ],
            403,
        ),
        (
            [
                (b"host", b"localhost"),
                (b"referer", b"http://localhost/one"),
                (b"Referer", b"http://localhost/two"),
            ],
            403,
        ),
    ],
)
async def test_missing_or_duplicate_security_singletons_fail_closed(
    headers: list[tuple[bytes, bytes]], expected_status: int
) -> None:
    messages = await _run(headers)
    assert _status(messages) == expected_status
    response_headers = _headers(messages)
    assert response_headers[b"x-content-type-options"] == b"nosniff"
    assert b"content-security-policy" in response_headers


async def test_origin_and_referer_may_coexist_when_both_are_consistent() -> None:
    messages = await _run(
        [
            (b"host", b"localhost"),
            (b"origin", b"http://localhost"),
            (b"referer", b"http://localhost/form"),
        ]
    )
    assert _status(messages) == 200


async def test_origin_does_not_hide_an_inconsistent_referer() -> None:
    messages = await _run(
        [
            (b"host", b"localhost"),
            (b"origin", b"http://localhost"),
            (b"referer", b"http://evil.example/form"),
        ]
    )
    assert _status(messages) == 403
