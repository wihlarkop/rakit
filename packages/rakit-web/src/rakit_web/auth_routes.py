"""Login/logout routes: session-cookie issuance, CSRF-token issuance, and
login rate limiting. Wired into `Admin.asgi()` only when both an
`AuthBackend` and a `SessionStore` are configured -- an `Admin` with
neither remains exactly as unauthenticated as before this module existed.
"""

import hmac
import secrets

from rakit_core.auth import AuthBackend, SessionStore, normalize_identifier
from rakit_core.errors import ErrorCode, RakitError
from starlette.exceptions import HTTPException
from starlette.requests import Request
from starlette.responses import PlainTextResponse, RedirectResponse, Response
from starlette.routing import Route
from starlette.templating import Jinja2Templates

from ._paths import mounted_path as _mounted_path
from .security.cookies import CSRF_COOKIE_NAME, LOGIN_CSRF_COOKIE_NAME, SESSION_COOKIE_NAME
from .security.csrf import CsrfService
from .security.middleware import resolve_client_ip
from .security.rate_limit import RateLimiter
from .security.validation import TrustedProxyNetwork

CSRF_HEADER_NAME = "x-csrf-token"
CSRF_FORM_FIELD = "csrf_token"
LOGIN_CSRF_FORM_FIELD = "login_csrf_token"
_MAX_LOGIN_FIELDS = 8
_MAX_LOGIN_IDENTIFIER_LENGTH = 320
_MAX_LOGIN_PASSWORD_LENGTH = 1024
_MAX_LOGIN_CSRF_LENGTH = 512
_MAX_LOGIN_MULTIPART_PART_SIZE = 64 * 1024


async def _parse_login_form(request: Request) -> tuple[str, str, str] | None:
    try:
        form = await request.form(
            max_files=0,
            max_fields=_MAX_LOGIN_FIELDS,
            max_part_size=_MAX_LOGIN_MULTIPART_PART_SIZE,
        )
    except HTTPException:
        return None

    items = form.multi_items()
    if len(items) > _MAX_LOGIN_FIELDS:
        return None
    if (
        any(
            sum(name == required for name, _ in items) != 1
            for required in ("identifier", "password")
        )
        or sum(name == LOGIN_CSRF_FORM_FIELD for name, _ in items) > 1
    ):
        return None
    identifier = form.get("identifier")
    password = form.get("password")
    csrf_token = form.get(LOGIN_CSRF_FORM_FIELD, "")
    if not all(isinstance(value, str) for value in (identifier, password, csrf_token)):
        return None
    assert isinstance(identifier, str)
    assert isinstance(password, str)
    assert isinstance(csrf_token, str)
    if (
        len(identifier) > _MAX_LOGIN_IDENTIFIER_LENGTH
        or len(password) > _MAX_LOGIN_PASSWORD_LENGTH
        or len(csrf_token) > _MAX_LOGIN_CSRF_LENGTH
    ):
        return None
    return identifier.strip(), password, csrf_token


async def _submitted_csrf_token(request: Request) -> str | None:
    header_value = request.headers.get(CSRF_HEADER_NAME)
    if header_value is not None:
        return header_value
    form = await request.form()
    field_value = form.get(CSRF_FORM_FIELD)
    return str(field_value) if field_value is not None else None


async def _verify_csrf(request: Request, csrf_service: CsrfService, *, session_id: str) -> bool:
    """Double-submit CSRF validation: the cookie value and the
    submitted (form field or header) value must match byte-for-byte
    (constant-time compare, since both are secrets an attacker
    shouldn't be able to learn via timing), *and* the token itself must
    be a genuine, unexpired CsrfService token bound to this exact
    `session_id` -- matching cookie/submitted values alone would also
    accept a forged pair copied from a different session.
    """
    cookie_value = request.cookies.get(CSRF_COOKIE_NAME)
    submitted_value = await _submitted_csrf_token(request)
    if cookie_value is None or submitted_value is None:
        return False
    if not hmac.compare_digest(cookie_value, submitted_value):
        return False
    return csrf_service.verify(cookie_value, session_id=session_id)


def _verify_login_csrf(request: Request, form_value: str | None) -> bool:
    """Pure double-submit check for the login POST.

    Login is the only unauthenticated state-changing endpoint, so there is
    no `session_id` yet to bind a `CsrfService` token to. A random value
    issued with the login page and echoed back in the form is enough: an
    attacker forging a cross-site login POST cannot read the victim's
    cookie to populate the field. `SecurityMiddleware`'s Origin check
    deliberately permits a request that sends neither Origin nor Referer,
    so without this the login endpoint would have no CSRF defence at all
    against such a client.
    """
    cookie_value = request.cookies.get(LOGIN_CSRF_COOKIE_NAME)
    if cookie_value is None or form_value is None:
        return False
    return hmac.compare_digest(cookie_value, form_value)


def build_auth_routes(
    *,
    auth_backend: AuthBackend,
    session_store: SessionStore,
    csrf_service: CsrfService,
    rate_limiter: RateLimiter,
    templates: Jinja2Templates,
    admin_id: str,
    secure_cookies: bool,
    trusted_proxies: tuple[TrustedProxyNetwork, ...] = (),
) -> list[Route]:
    def _render_login(request: Request, *, error: str | None, status_code: int = 200) -> Response:
        """Render the login page, always issuing a fresh pre-session CSRF
        token -- including on a rejected attempt, so the user can retry
        without being stuck holding a token the server no longer accepts."""
        token = secrets.token_urlsafe(32)
        response = templates.TemplateResponse(
            request,
            "auth/login.html",
            {
                "error": error,
                "login_url": _mounted_path(request, "/auth/login"),
                "login_csrf_token": token,
                "login_csrf_field": LOGIN_CSRF_FORM_FIELD,
            },
            status_code=status_code,
            headers={"Cache-Control": "no-store"},
        )
        response.set_cookie(
            LOGIN_CSRF_COOKIE_NAME,
            token,
            httponly=True,
            secure=secure_cookies,
            samesite="lax",
            path=_mounted_path(request, "/") or "/",
        )
        return response

    async def login_get(request: Request) -> Response:
        return _render_login(request, error=None)

    async def login_post(request: Request) -> Response:
        parsed_form = await _parse_login_form(request)
        if parsed_form is None:
            return PlainTextResponse(
                "Invalid login form", status_code=400, headers={"Cache-Control": "no-store"}
            )
        identifier, password, submitted_login_csrf = parsed_form
        identifier = normalize_identifier(identifier)
        client_ip = resolve_client_ip(request, trusted_proxies)

        if not _verify_login_csrf(request, submitted_login_csrf):
            # Checked before the credentials are even looked at, so a
            # forged cross-site login POST never reaches the auth backend
            # (and never consumes a rate-limit slot for the victim's
            # identifier).
            return PlainTextResponse(
                "Invalid CSRF token", status_code=403, headers={"Cache-Control": "no-store"}
            )

        limiter_result = await rate_limiter.check(
            admin_id=admin_id, identifier=identifier, client_ip=client_ip
        )
        if not isinstance(limiter_result, bool):
            raise RakitError(
                code=ErrorCode.INTERNAL_ERROR,
                message="Rate limiter returned an invalid result",
                status_code=500,
            )
        if not limiter_result:
            return _render_login(
                request, error="Too many attempts. Try again later.", status_code=429
            )

        # Deliberately identical response for "no such identifier" and
        # "identifier exists but password is wrong" -- distinguishing them
        # would let this endpoint be used to enumerate valid identifiers.
        principal = await auth_backend.authenticate(identifier, password)
        if principal is None or not principal.authenticated:
            return _render_login(request, error="Invalid credentials.", status_code=401)

        raw_token, record = await session_store.create(principal)
        try:
            csrf_token = csrf_service.issue(record)
        except Exception:
            await session_store.revoke(record.session_id)
            raise

        response = RedirectResponse(url=_mounted_path(request, "/"), status_code=303)
        cookie_path = _mounted_path(request, "/") or "/"
        response.set_cookie(
            SESSION_COOKIE_NAME,
            raw_token,
            httponly=True,
            secure=secure_cookies,
            samesite="lax",
            path=cookie_path,
        )
        # Not HttpOnly: the double-submit CSRF pattern requires client-side
        # (form/JS) code to read this value and echo it back on mutations.
        response.set_cookie(
            CSRF_COOKIE_NAME,
            csrf_token,
            httponly=False,
            secure=secure_cookies,
            samesite="lax",
            path=cookie_path,
        )
        return response

    async def logout_post(request: Request) -> Response:
        raw_token = request.cookies.get(SESSION_COOKIE_NAME)
        record = await session_store.resolve(raw_token) if raw_token else None

        # CSRF is only enforced when there's an active, authenticated
        # session to protect -- logging out with no session at all (already
        # logged out, or never logged in) is a safe no-op with nothing for
        # CSRF to defend.
        if record is not None:
            if not await _verify_csrf(request, csrf_service, session_id=record.session_id):
                return PlainTextResponse(
                    "Invalid CSRF token", status_code=403, headers={"Cache-Control": "no-store"}
                )
            await session_store.revoke(record.session_id)

        response = RedirectResponse(url=_mounted_path(request, "/auth/login"), status_code=303)
        cookie_path = _mounted_path(request, "/") or "/"
        response.delete_cookie(SESSION_COOKIE_NAME, path=cookie_path)
        response.delete_cookie(CSRF_COOKIE_NAME, path=cookie_path)
        return response

    return [
        Route("/auth/login", login_get, methods=["GET"], name="rakit.auth.login"),
        Route("/auth/login", login_post, methods=["POST"], name="rakit.auth.login.submit"),
        Route("/auth/logout", logout_post, methods=["POST"], name="rakit.auth.logout"),
    ]
