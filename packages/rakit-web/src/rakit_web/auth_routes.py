"""Login/logout routes: session-cookie issuance, CSRF-token issuance, and
login rate limiting. Wired into `Admin.asgi()` only when both an
`AuthBackend` and a `SessionStore` are configured -- an `Admin` with
neither remains exactly as unauthenticated as before this module existed.
"""

from rakit_core.auth import AuthBackend, SessionStore
from starlette.requests import Request
from starlette.responses import RedirectResponse, Response
from starlette.routing import Route
from starlette.templating import Jinja2Templates

from .security.csrf import CsrfService
from .security.rate_limit import LoginRateLimiter

SESSION_COOKIE_NAME = "rakit_session"
CSRF_COOKIE_NAME = "rakit_csrf"


def _mounted_path(request: Request, path: str) -> str:
    root_path = request.scope.get("root_path", "").rstrip("/")
    return f"{root_path}{path}"


def build_auth_routes(
    *,
    auth_backend: AuthBackend,
    session_store: SessionStore,
    csrf_service: CsrfService,
    rate_limiter: LoginRateLimiter,
    templates: Jinja2Templates,
    admin_id: str,
    secure_cookies: bool,
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
        client_ip = request.client.host if request.client else "unknown"
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
        if raw_token:
            record = await session_store.resolve(raw_token)
            if record is not None:
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
