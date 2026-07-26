"""Request-time authentication and route authorization.

Two raw ASGI middlewares, applied only when authentication is configured:

- `PrincipalMiddleware` resolves the session cookie into an immutable
  `Principal` on `scope["state"]["principal"]` for every request (falling
  back to `ANONYMOUS_PRINCIPAL`);
- `AuthorizationMiddleware` gates each request against an explicit
  permission requirement resolved from its path.

Both are raw ASGI wrappers, not `BaseHTTPMiddleware`, for the same reason
`RequestContextMiddleware` is: avoiding the separate-task contextvars
pitfall, and so a rejection short-circuits without ever invoking the
downstream app.
"""

from collections.abc import Callable

from rakit_core.auth import ANONYMOUS_PRINCIPAL, AuthBackend, Principal, SessionStore
from rakit_core.permissions import PermissionRequirement
from starlette.requests import Request
from starlette.responses import PlainTextResponse, RedirectResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from .._paths import mounted_path
from .cookies import SESSION_COOKIE_NAME

LOGIN_PATH = "/auth/login"
LOGOUT_PATH = "/auth/logout"

# Paths that must remain reachable without authentication. `/auth/login`
# above all -- gating it would make the admin unreachable (a redirect loop
# to a route that itself redirects). System health/readiness and bundled
# static assets carry no resource data and are needed by probes and by the
# login page itself.
_PUBLIC_PATH_PREFIXES = (LOGIN_PATH, LOGOUT_PATH, "/_system/")


def is_public_path(path: str) -> bool:
    return any(path == prefix or path.startswith(prefix) for prefix in _PUBLIC_PATH_PREFIXES)


def admin_relative_path(request: Request) -> str:
    """The request path relative to this admin's own mount point.

    `request.url.path` is the *full* external path, so under a mount it
    carries the prefix (`/admin/auth/login`). Route requirements are
    declared in admin-relative terms (`/auth/login`, `/widgets`), so the
    mount prefix must be stripped before matching -- otherwise a mounted
    admin would gate its own login route and redirect-loop.
    """
    root_path = request.scope.get("root_path", "").rstrip("/")
    path = request.url.path
    if root_path and path.startswith(root_path):
        return path[len(root_path) :] or "/"
    return path


class PrincipalMiddleware:
    """Resolves the session cookie into a `Principal` on every request.

    Re-resolves the principal from the backend on each request (not from
    anything cached in the session row), so a deactivated user or a changed
    permission set takes effect immediately rather than staying frozen at
    login time. A session that no longer resolves, or whose subject no
    longer resolves to an active principal, yields `ANONYMOUS_PRINCIPAL` --
    never a partially-authenticated state.
    """

    def __init__(
        self, app: ASGIApp, *, auth_backend: AuthBackend, session_store: SessionStore
    ) -> None:
        self.app = app
        self._auth_backend = auth_backend
        self._session_store = session_store

    async def _resolve(self, request: Request) -> Principal:
        raw_token = request.cookies.get(SESSION_COOKIE_NAME)
        if not raw_token:
            return ANONYMOUS_PRINCIPAL
        record = await self._session_store.resolve(raw_token)
        if record is None:
            return ANONYMOUS_PRINCIPAL
        principal = await self._auth_backend.resolve_principal(record.subject_id)
        if principal is None or not principal.authenticated:
            return ANONYMOUS_PRINCIPAL
        return principal

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        principal = await self._resolve(Request(scope, receive=receive))
        scope.setdefault("state", {})
        scope["state"]["principal"] = principal
        await self.app(scope, receive, send)


class AuthorizationMiddleware:
    """Gates each request against an explicit permission requirement.

    Requirements are resolved by path via a caller-supplied function, so
    the route -> permission mapping lives with the routes themselves rather
    than being inferred here. A path with no requirement is public.
    """

    def __init__(
        self,
        app: ASGIApp,
        *,
        requirement_for: Callable[[str], PermissionRequirement | None],
        superuser_bypass: bool = True,
    ) -> None:
        self.app = app
        self._requirement_for = requirement_for
        self._superuser_bypass = superuser_bypass

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request = Request(scope, receive=receive)
        requirement = self._requirement_for(admin_relative_path(request))
        if requirement is None:
            await self.app(scope, receive, send)
            return

        principal = scope.get("state", {}).get("principal", ANONYMOUS_PRINCIPAL)

        if not principal.authenticated:
            # An unauthenticated *browser* request is redirected to login
            # rather than 403'd, so a user landing on any admin URL gets a
            # usable login page. The target is always this admin's own
            # mounted login path -- never an attacker-supplied value -- so
            # it can't be turned into an open redirect.
            await RedirectResponse(
                url=mounted_path(request, LOGIN_PATH),
                status_code=303,
                headers={"Cache-Control": "no-store"},
            )(scope, receive, send)
            return

        if not requirement.matches(principal, superuser_bypass=self._superuser_bypass):
            await PlainTextResponse(
                "Forbidden", status_code=403, headers={"Cache-Control": "no-store"}
            )(scope, receive, send)
            return

        await self.app(scope, receive, send)


def build_requirement_resolver(
    *, admin_id: str, resource_paths: dict[str, str]
) -> Callable[[str], PermissionRequirement | None]:
    """Map a request path to the permission it requires.

    `resource_paths` maps each compiled resource's base path (e.g.
    `/widgets`) to its `resource_id`. A resource's list, detail, and count
    routes all require the same `{admin_id}.resources.{resource_id}.read`
    permission -- Plan 03 ships read-only resources, so there is no
    per-operation split to make yet. Every other non-public path requires
    `{admin_id}.access` (the admin shell).
    """
    access_requirement = PermissionRequirement.all_of(f"{admin_id}.access")
    read_requirements = {
        path: PermissionRequirement.all_of(f"{admin_id}.resources.{resource_id}.read")
        for path, resource_id in resource_paths.items()
    }

    def resolve(path: str) -> PermissionRequirement | None:
        if is_public_path(path):
            return None
        for resource_path, requirement in read_requirements.items():
            if path == resource_path or path.startswith(f"{resource_path}/"):
                return requirement
        return access_requirement

    return resolve
