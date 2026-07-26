"""Login/logout routes: session-cookie issuance, CSRF-token issuance, and
login rate limiting. Wired into `Admin.asgi()` only when both an
`AuthBackend` and a `SessionStore` are configured -- an `Admin` with
neither remains exactly as unauthenticated as before this module existed.
"""

import hmac

from rakit_core.auth import AuthBackend, SessionStore
from starlette.requests import Request
from starlette.responses import PlainTextResponse, RedirectResponse, Response
from starlette.routing import Route
from starlette.templating import Jinja2Templates

from ._paths import mounted_path as _mounted_path
from .security.cookies import CSRF_COOKIE_NAME, SESSION_COOKIE_NAME
from .security.csrf import CsrfService
from .security.middleware import resolve_client_ip
from .security.rate_limit import LoginRateLimiter

CSRF_HEADER_NAME = "x-csrf-token"
CSRF_FORM_FIELD = "csrf_token"


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


def build_auth_routes(
    *,
    auth_backend: AuthBackend,
    session_store: SessionStore,
    csrf_service: CsrfService,
    rate_limiter: LoginRateLimiter,
    templates: Jinja2Templates,
    admin_id: str,
    secure_cookies: bool,
    trusted_proxies: tuple[str, ...] = (),
) -> list[Route]:
    async def login_get(request: Request) -> Response:
        return templates.TemplateResponse(
            request,
            "auth/login.html",
            {"error": None, "login_url": _mounted_path(request, "/auth/login")},
            headers={"Cache-Control": "no-store"},
        )

    async def login_post(request: Request) -> Response:
        form = await request.form()
        identifier = str(form.get("identifier", "")).strip()
        password = str(form.get("password", ""))
        client_ip = resolve_client_ip(request, trusted_proxies)
        login_url = _mounted_path(request, "/auth/login")

        if not rate_limiter.check(admin_id=admin_id, identifier=identifier, client_ip=client_ip):
            return templates.TemplateResponse(
                request,
                "auth/login.html",
                {"error": "Too many attempts. Try again later.", "login_url": login_url},
                status_code=429,
                headers={"Cache-Control": "no-store"},
            )

        # Deliberately identical response for "no such identifier" and
        # "identifier exists but password is wrong" -- distinguishing them
        # would let this endpoint be used to enumerate valid identifiers.
        principal = await auth_backend.authenticate(identifier, password)
        if principal is None or not principal.authenticated:
            return templates.TemplateResponse(
                request,
                "auth/login.html",
                {"error": "Invalid credentials.", "login_url": login_url},
                status_code=401,
                headers={"Cache-Control": "no-store"},
            )

        raw_token, record = await session_store.create(principal)
        csrf_token = csrf_service.issue(record.session_id)

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
