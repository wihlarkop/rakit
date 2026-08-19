from http import HTTPStatus
import ipaddress
from collections.abc import MutableMapping
from typing import Any
from urllib.parse import urlsplit

from starlette.requests import Request
from starlette.responses import PlainTextResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from .validation import TrustedProxyNetwork

_UNSAFE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})
_DEFAULT_MAX_BODY_SIZE = 10 * 1024 * 1024


_ORIGIN_SCHEMES = frozenset({"http", "https"})
_MIN_PORT = 1
_MAX_PORT = 65535
# Everything a registered hostname may legally contain. Deliberately a
# strict allow-list: whitespace, control characters, "@", ",", "/", "?" and
# "#" are all how a malformed or deliberately-ambiguous authority smuggles a
# second host past a parser, so anything not on this list is malformed.
_HOSTNAME_CHARACTERS = frozenset("abcdefghijklmnopqrstuvwxyz0123456789-._")


class _BodyTooLarge(BaseException):
    """Private control signal that downstream exception middleware must not turn into 500."""


def _effective_port(scheme: str, port: int | None) -> int:
    if port is not None:
        return port
    return 443 if scheme == "https" else 80


def _parse_port(raw_port: str) -> int | None:
    if not raw_port.isdigit():  # also rejects "", "-1", "+1", " 80", "8_0"
        return None
    port = int(raw_port)
    if not _MIN_PORT <= port <= _MAX_PORT:
        return None
    return port


def parse_authority(raw_authority: str) -> tuple[str, int | None] | None:
    """Split a `host[:port]` authority into its parts, or `None` if it is
    malformed in any way.

    Written to be total: it never raises, whatever bytes arrive. That is the
    whole point. The previous implementation reached `urlsplit(...).port`
    and `.hostname`, both of which raise `ValueError` on input a client
    fully controls (`:abc`, `:99999`, an unterminated `[::1`), so a
    malformed header produced a 500 from inside the middleware whose job is
    to reject it.
    """
    if not raw_authority or raw_authority.strip() != raw_authority:
        return None

    if raw_authority.startswith("["):
        closing_bracket = raw_authority.find("]")
        if closing_bracket == -1:
            return None
        host = raw_authority[: closing_bracket + 1]
        remainder = raw_authority[closing_bracket + 1 :]
        try:
            ipaddress.IPv6Address(host[1:-1])
        except ValueError:
            return None
        if not remainder:
            return (host.lower(), None)
        if not remainder.startswith(":"):
            return None  # junk between "]" and the port
        port = _parse_port(remainder[1:])
        return None if port is None else (host.lower(), port)

    host, separator, raw_port = raw_authority.partition(":")
    if not host or not set(host.lower()) <= _HOSTNAME_CHARACTERS:
        return None
    if not separator:
        return (host.lower(), None)
    port = _parse_port(raw_port)
    return None if port is None else (host.lower(), port)


def _canonical_origin(scheme: str, authority: str) -> tuple[str, str, int] | None:
    """Canonicalize scheme + authority for exact same-origin comparison --
    deliberately distinct from allowed-host validation (which only ever
    checks the hostname). A request's own origin and a submitted
    Origin/Referer's are built by this same function, so the two are never
    accidentally conflated.
    """
    scheme = scheme.lower()
    if scheme not in _ORIGIN_SCHEMES:
        return None
    parsed = parse_authority(authority)
    if parsed is None:
        return None
    host, port = parsed
    return (scheme, host, _effective_port(scheme, port))


def _parse_origin(value: str, *, allow_path: bool) -> tuple[str, str, int] | None:
    """Parse an Origin/Referer header value into a canonical origin tuple,
    or `None` if it doesn't resolve to one at all -- a literal `"null"`, a
    scheme-less or otherwise malformed value, a non-web scheme, or an
    authority carrying userinfo. Callers must treat `None` as a mismatch,
    never as "nothing to check."

    `allow_path` distinguishes the two headers. Per RFC 6454 an Origin is a
    bare `scheme://host[:port]`, so a path, query, or fragment means the
    value is not an Origin at all. A Referer legitimately carries all three,
    and only its authority is compared.
    """
    try:
        parsed = urlsplit(value)
    except ValueError:
        return None
    if not allow_path and (parsed.path or parsed.query or parsed.fragment):
        return None
    # `netloc`, not `hostname`/`port`: those properties re-parse and raise on
    # exactly the malformed input this function exists to absorb. Userinfo is
    # rejected outright rather than stripped -- `http://localhost@evil.example`
    # reads as "localhost" to a careless human and "evil.example" to a
    # parser, and no legitimate Origin or Referer carries credentials.
    if "@" in parsed.netloc:
        return None
    return _canonical_origin(parsed.scheme, parsed.netloc)


def resolve_client_ip(
    request: Request, trusted_proxies: tuple[TrustedProxyNetwork, ...]
) -> str | None:
    """Return the real client IP, honouring `X-Forwarded-For` only when the
    directly-connecting peer is inside a configured trusted-proxy CIDR.

    Proxy headers are never trusted automatically -- an untrusted direct
    peer's claimed `X-Forwarded-For` is ignored entirely, since accepting it
    would let any client spoof its own rate-limit/audit identity.
    """
    direct_ip = request.client.host if request.client else None
    if direct_ip is None:
        return None
    try:
        direct_addr = ipaddress.ip_address(direct_ip)
    except ValueError:
        return None
    canonical_direct = str(direct_addr)
    if not trusted_proxies or not any(direct_addr in network for network in trusted_proxies):
        return canonical_direct
    forwarded_fields = request.headers.getlist("x-forwarded-for")
    if not forwarded_fields:
        return canonical_direct

    raw_hops = [
        raw_hop for forwarded_field in forwarded_fields for raw_hop in forwarded_field.split(",")
    ]
    for raw_hop in reversed(raw_hops):
        try:
            hop = ipaddress.ip_address(raw_hop.strip())
        except ValueError:
            return None
        if any(hop in network for network in trusted_proxies):
            continue
        return str(hop)
    return None


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

    The body-size limit validates Content-Length and independently counts
    bytes delivered by the ASGI receive stream, so absent or dishonest
    declarations cannot bypass it.
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
        response_started = False
        received_size = 0

        async def send_with_security_headers(message: MutableMapping[str, Any]) -> None:
            nonlocal response_started
            if message["type"] == "http.response.start":
                response_started = True
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

        # Every rejection below goes through `send_with_security_headers`
        # too, not the raw `send`. A response this middleware generates
        # itself must not be the least-protected response the app can emit
        # -- it would otherwise skip the very headers this middleware
        # exists to add.
        # A Host that cannot be parsed at all and a Host that parses but
        # isn't allowed are both 400: the request line is unusable either
        # way, and distinguishing them in the response would only tell a
        # prober which of the two it hit.
        raw_headers = scope.get("headers", ())

        def singleton_values(name: bytes) -> list[str]:
            return [
                value.decode("latin-1")
                for raw_name, value in raw_headers
                if raw_name.lower() == name
            ]

        host_values = singleton_values(b"host")
        origin_values = singleton_values(b"origin")
        referer_values = singleton_values(b"referer")
        if len(host_values) != 1:
            await PlainTextResponse("Invalid host header", status_code=HTTPStatus.BAD_REQUEST)(
                scope, receive, send_with_security_headers
            )
            return
        if len(origin_values) > 1 or len(referer_values) > 1:
            await PlainTextResponse("Invalid request origin", status_code=HTTPStatus.FORBIDDEN)(
                scope, receive, send_with_security_headers
            )
            return

        authority = parse_authority(host_values[0])
        if authority is None or authority[0] not in self._allowed_hosts:
            await PlainTextResponse("Invalid host header", status_code=HTTPStatus.BAD_REQUEST)(
                scope, receive, send_with_security_headers
            )
            return

        if request.method in _UNSAFE_METHODS:
            request_scheme = request.url.scheme.lower()
            host, port = authority
            request_origin = (
                (request_scheme, host, _effective_port(request_scheme, port))
                if request_scheme in _ORIGIN_SCHEMES
                else None
            )
            sources = (
                (origin_values[0], False) if origin_values else None,
                (referer_values[0], True) if referer_values else None,
            )
            for source_entry in sources:
                if source_entry is None:
                    continue
                source, allow_path = source_entry
                # A *present* Origin/Referer that doesn't resolve to a
                # canonical origin at all (a literal "null" from a
                # sandboxed iframe, or a malformed/scheme-less value) is
                # exactly the shape of value a cross-origin attacker would
                # send -- treat it as a mismatch, not as "nothing to
                # check." Absence of both headers entirely is handled
                # separately above and is not rejected.
                #
                # This compares against the *request's own* scheme/host/
                # port, not against `allowed_hosts` -- same-origin
                # validation and trusted-host validation are deliberately
                # separate checks. Hostname alone is not enough: an Origin
                # matching the hostname but differing in scheme or port
                # (e.g. https://localhost:4443 against a plain
                # http://localhost request) must still be rejected.
                source_origin = _parse_origin(source, allow_path=allow_path)
                if source_origin is None or source_origin != request_origin:
                    await PlainTextResponse("Invalid request origin", status_code=HTTPStatus.FORBIDDEN)(
                        scope, receive, send_with_security_headers
                    )
                    return

        content_lengths = [
            value for name, value in raw_headers if name.lower() == b"content-length"
        ]
        invalid_content_length = len(content_lengths) > 1
        declared_size: int | None = None
        if len(content_lengths) == 1:
            raw_length = content_lengths[0]
            invalid_content_length = not raw_length.isdigit()
            if not invalid_content_length:
                significant_length = raw_length.lstrip(b"0") or b"0"
                max_body_size_text = str(self._max_body_size).encode("ascii")
                if len(significant_length) > len(max_body_size_text):
                    declared_size = self._max_body_size + 1
                else:
                    declared_size = int(significant_length)
        if invalid_content_length or (
            declared_size is not None and declared_size > self._max_body_size
        ):
            await PlainTextResponse("Request entity too large", status_code=HTTPStatus.REQUEST_ENTITY_TOO_LARGE)(
                scope, receive, send_with_security_headers
            )
            return

        async def limited_receive() -> MutableMapping[str, Any]:
            nonlocal received_size
            message = await receive()
            if message["type"] == "http.request":
                received_size += len(message.get("body", b""))
                if received_size > self._max_body_size:
                    raise _BodyTooLarge
            return message

        try:
            await self.app(scope, limited_receive, send_with_security_headers)
        except _BodyTooLarge:
            if not response_started:
                await PlainTextResponse("Request entity too large", status_code=HTTPStatus.REQUEST_ENTITY_TOO_LARGE)(
                    scope, receive, send_with_security_headers
                )
