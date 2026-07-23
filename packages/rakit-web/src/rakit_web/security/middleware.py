import ipaddress
from collections.abc import MutableMapping
from typing import Any
from urllib.parse import urlsplit

from starlette.requests import Request
from starlette.responses import PlainTextResponse
from starlette.types import ASGIApp, Receive, Scope, Send

_UNSAFE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})
_DEFAULT_MAX_BODY_SIZE = 10 * 1024 * 1024


def _host_from_url(value: str) -> str | None:
    return urlsplit(value).hostname


def _host_without_port(raw_host: str) -> str:
    """Strip a trailing `:port` from a `Host` header value, without
    mangling a bracketed IPv6 literal (`[::1]` or `[::1]:8000`) -- a naive
    `.split(":")[0]` truncates `[::1]` to `[`, which can never match an
    allowed-hosts entry of `"[::1]"`."""
    if raw_host.startswith("["):
        closing_bracket = raw_host.find("]")
        if closing_bracket != -1:
            return raw_host[: closing_bracket + 1]
        return raw_host
    return raw_host.split(":", 1)[0]


def resolve_client_ip(request: Request, trusted_proxies: tuple[str, ...]) -> str:
    """Return the real client IP, honouring `X-Forwarded-For` only when the
    directly-connecting peer is inside a configured trusted-proxy CIDR.

    Proxy headers are never trusted automatically -- an untrusted direct
    peer's claimed `X-Forwarded-For` is ignored entirely, since accepting it
    would let any client spoof its own rate-limit/audit identity.
    """
    direct_ip = request.client.host if request.client else "unknown"
    if not trusted_proxies or direct_ip == "unknown":
        return direct_ip
    try:
        direct_addr = ipaddress.ip_address(direct_ip)
    except ValueError:
        return direct_ip
    is_trusted_peer = any(
        direct_addr in ipaddress.ip_network(cidr, strict=False) for cidr in trusted_proxies
    )
    if not is_trusted_peer:
        return direct_ip
    forwarded_for = request.headers.get("x-forwarded-for")
    if not forwarded_for:
        return direct_ip
    return forwarded_for.split(",")[0].strip()


class SecurityMiddleware:
    """Raw ASGI middleware enforcing the baseline security posture on every
    request, whether or not authentication is configured: trusted-host
    validation, mutation Origin/Referer validation, a request body size
    limit, and response security headers.

    A raw ASGI wrapper (not `BaseHTTPMiddleware`) for the same reason
    `RequestContextMiddleware` in `admin.py` is one: avoiding the separate-task
    contextvars-propagation pitfall, and so short-circuit rejections
    (untrusted host, oversized body, cross-origin mutation) never invoke the
    downstream app at all.

    Bounded scope: the body-size limit only inspects a declared
    `Content-Length` header, not actual bytes streamed -- a request that
    omits `Content-Length` (chunked transfer) is not currently bounded by
    this middleware. True streaming enforcement is deferred; see
    `plan-03-design-decisions.md`.
    """

    def __init__(
        self,
        app: ASGIApp,
        *,
        allowed_hosts: tuple[str, ...],
        content_security_policy_enabled: bool,
        max_body_size: int = _DEFAULT_MAX_BODY_SIZE,
    ) -> None:
        self.app = app
        self._allowed_hosts = allowed_hosts
        self._csp_enabled = content_security_policy_enabled
        self._max_body_size = max_body_size

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request = Request(scope, receive=receive)

        host = _host_without_port(request.headers.get("host") or "")
        if host not in self._allowed_hosts:
            await PlainTextResponse("Invalid host header", status_code=400)(scope, receive, send)
            return

        if request.method in _UNSAFE_METHODS:
            source = request.headers.get("origin") or request.headers.get("referer")
            if source is not None:
                # A *present* Origin/Referer that doesn't resolve to a
                # hostname at all (a literal "null" from a sandboxed
                # iframe, or a malformed/scheme-less value) is exactly the
                # shape of value a cross-origin attacker would send --
                # treat it as a mismatch, not as "nothing to check."
                # Absence of both headers entirely is handled separately
                # above and is not rejected.
                source_host = _host_from_url(source)
                if source_host not in self._allowed_hosts:
                    await PlainTextResponse("Invalid request origin", status_code=403)(
                        scope, receive, send
                    )
                    return

        content_length = request.headers.get("content-length")
        if content_length is not None:
            try:
                declared_size = int(content_length)
            except ValueError:
                declared_size = None
            if declared_size is not None and declared_size > self._max_body_size:
                await PlainTextResponse("Request entity too large", status_code=413)(
                    scope, receive, send
                )
                return

        async def send_with_security_headers(message: MutableMapping[str, Any]) -> None:
            if message["type"] == "http.response.start":
                existing = {name.decode("latin-1").lower() for name, _ in message["headers"]}
                extra: list[tuple[bytes, bytes]] = []

                def add(name: str, value: str) -> None:
                    if name not in existing:
                        extra.append((name.encode("latin-1"), value.encode("latin-1")))

                add("x-content-type-options", "nosniff")
                add("referrer-policy", "same-origin")
                add("permissions-policy", "geolocation=(), camera=(), microphone=()")
                add("cross-origin-opener-policy", "same-origin")
                add("x-frame-options", "DENY")
                add("cache-control", "no-store")
                if self._csp_enabled:
                    add(
                        "content-security-policy",
                        "default-src 'self'; frame-ancestors 'none'; base-uri 'self'",
                    )
                message["headers"] = list(message["headers"]) + extra
            await send(message)

        await self.app(scope, receive, send_with_security_headers)
