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

from collections.abc import Callable, Mapping
from urllib.parse import unquote

from rakit_core.auth import ANONYMOUS_PRINCIPAL, AuthBackend, Principal, SessionStore
from rakit_core.permissions import PermissionRequirement
from starlette.requests import Request
from starlette.responses import PlainTextResponse, RedirectResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from .._paths import mounted_path
from .cookies import SESSION_COOKIE_NAME

LOGIN_PATH = "/auth/login"
LOGOUT_PATH = "/auth/logout"

# Paths that must remain reachable without authentication. `/auth/login`
# above all -- gating it would make the admin unreachable (a redirect loop
# to a route that itself redirects). System health/readiness and bundled
# static assets carry no resource data and are needed by probes and by the
# login page itself.
# Exactly-public paths, and roots whose descendants are public.
_PUBLIC_EXACT_PATHS = (LOGIN_PATH, LOGOUT_PATH)
_PUBLIC_SUBTREE_ROOTS = ("/_system",)


def is_public_path(path: str) -> bool:
    """Whether `path` is explicitly public.

    Deliberately *not* a bare `startswith`: that would make any path merely
    beginning with a public root public too, so `/auth/loginX`,
    `/auth/login-and-more`, or a future route under `/_systemfoo` would
    bypass authorization entirely. Login/logout match exactly; only
    `/_system` has public descendants (health, readiness, bundled static
    assets), matched at a `/` segment boundary.

    A path carrying any dot segment -- literal or percent-encoded -- is
    never public. An un-normalized traversal like `/auth/login/../widgets`
    begins with a public root but does not *resolve* under one, so it fails
    closed rather than being classified from its literal prefix.
    """
    if _has_dot_segment(path):
        return False
    if path in _PUBLIC_EXACT_PATHS:
        return True
    return any(path.startswith(f"{root}/") for root in _PUBLIC_SUBTREE_ROOTS)


def _has_dot_segment(path: str) -> bool:
    # Percent-decode first so an encoded separator (%2f) or encoded dot
    # (%2e) can't hide a traversal from the segment check.
    decoded = unquote(path)
    return any(segment in (".", "..") for segment in decoded.split("/"))


def _session_cookie_deletion(cookie_path: str) -> tuple[bytes, bytes]:
    """A `Set-Cookie` header that expires the session cookie.

    Built by hand rather than via `Response.delete_cookie` because this
    middleware is raw ASGI: it appends a header to whatever response the
    downstream app produced instead of constructing one of its own. The
    attributes must match how the cookie was set (see `auth_routes`), or the
    browser keeps the original alongside the deletion.
    """
    value = (
        f"{SESSION_COOKIE_NAME}=; Path={cookie_path}; Max-Age=0; "
        "Expires=Thu, 01 Jan 1970 00:00:00 GMT; HttpOnly; SameSite=lax"
    )
    return (b"set-cookie", value.encode("latin-1"))


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

    async def _resolve(self, request: Request) -> tuple[Principal, bool, str | None]:
        """Resolve the request's principal, and report whether a session
        cookie was present but no longer usable.

        The second element drives cookie clearing. A cookie that resolves to
        nothing is not merely useless: it costs a session lookup and a
        backend lookup on every subsequent request to reach the same
        anonymous answer, and leaves a credential-shaped value sitting in
        the browser.
        """
        raw_token = request.cookies.get(SESSION_COOKIE_NAME)
        if not raw_token:
            return ANONYMOUS_PRINCIPAL, False, None
        record = await self._session_store.resolve(raw_token)
        if record is None:
            return ANONYMOUS_PRINCIPAL, True, None
        principal = await self._auth_backend.resolve_principal(record.subject_id)
        if principal is None or not principal.authenticated:
            # Revoke, don't just ignore. Treating this as anonymous for the
            # current request left the session row live and the cookie in
            # place, so re-enabling a disabled account silently restored the
            # *same* pre-deactivation session. Disabling an account has to
            # end its sessions, not pause them.
            await self._session_store.revoke(record.session_id)
            return ANONYMOUS_PRINCIPAL, True, None
        return principal, False, record.session_id

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        request = Request(scope, receive=receive)
        principal, clear_session_cookie, session_id = await self._resolve(request)
        scope.setdefault("state", {})
        scope["state"]["principal"] = principal
        if session_id is not None:
            # The opaque identifier is request-private state, not a response
            # field.  Write routes use it to bind CSRF/submission tokens to
            # the live session already resolved by this middleware.
            scope["state"]["session_id"] = session_id
        if not clear_session_cookie:
            await self.app(scope, receive, send)
            return

        cookie_path = mounted_path(request, "/") or "/"
        deletion = _session_cookie_deletion(cookie_path)

        async def send_clearing_session_cookie(message: Message) -> None:
            if message["type"] == "http.response.start":
                message["headers"] = [*message["headers"], deletion]
            await send(message)

        await self.app(scope, receive, send_clearing_session_cookie)


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
        requirement_for: Callable[..., PermissionRequirement | None],
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
        requirement = self._requirement_for(admin_relative_path(request), request.method)
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
    *,
    admin_id: str,
    resource_paths: dict[str, str],
    writable_resources: frozenset[str] = frozenset(),
    action_requirements: Mapping[str, PermissionRequirement] | None = None,
) -> Callable[..., PermissionRequirement | None]:
    """Map a request path to the permission it requires.

    `resource_paths` maps each compiled resource's base path (e.g.
    `/widgets`) to its `resource_id`. A resource's list, detail, and count
    routes all require the same `{admin_id}.resources.{resource_id}.read`
    permission -- Plan 03 ships read-only resources, so there is no
    per-operation split to make yet. Every other non-public path requires
    `{admin_id}.access` (the admin shell).

    `action_requirements` maps each compiled action route pattern (the
    compiler-owned path, with a literal `{identity}` segment for RECORD
    actions) to its exact compiled permission. Action routes are matched
    before resource prefixes so a path like `/orders/_actions/export` is
    never misclassified as an ordinary resource read, and a principal
    holding only `orders.read`/`orders.update` can never reach an action
    through the middleware. The action route handler independently
    re-evaluates the same compiled requirement.
    """
    access_requirement = PermissionRequirement.all_of(f"{admin_id}.access")
    read_requirements = {
        path: (
            resource_id,
            PermissionRequirement.all_of(f"{admin_id}.resources.{resource_id}.read"),
        )
        for path, resource_id in resource_paths.items()
    }

    action_patterns = [
        (pattern.strip("/").split("/"), requirement)
        for pattern, requirement in (action_requirements or {}).items()
    ]
    action_patterns.sort(key=lambda item: len(item[0]), reverse=True)

    # Longest prefix first: with nested resource paths (`/orders` and
    # `/orders/lines`), the most specific match must win. Returning
    # whichever happened to be checked first would gate `/orders/lines`
    # with `/orders`'s permission, letting a user holding only
    # `orders.read` reach a resource they have no permission for.
    ordered_requirements = sorted(
        read_requirements.items(), key=lambda item: len(item[0]), reverse=True
    )

    def resolve(path: str, method: str = "GET") -> PermissionRequirement | None:
        if is_public_path(path):
            return None
        segments = path.strip("/").split("/")
        for pattern_segments, requirement in action_patterns:
            if len(pattern_segments) == len(segments) and all(
                pattern_segment == segment or pattern_segment == "{identity}"
                for pattern_segment, segment in zip(pattern_segments, segments, strict=True)
            ):
                return requirement
        for resource_path, (resource_id, requirement) in ordered_requirements:
            if path == resource_path or path.startswith(f"{resource_path}/"):
                if resource_id in writable_resources:
                    suffix = path[len(resource_path) :].strip("/").split("/")
                    operation: str | None = None
                    if suffix == ["new"]:
                        operation = "create"
                    elif len(suffix) == 2 and suffix[1] in {"edit", "delete"}:
                        operation = "update" if suffix[1] == "edit" else "delete"
                    elif len(suffix) >= 2 and suffix[1] == "_relationships":
                        # Candidate/fragment reads are part of a pending graph
                        # mutation, so they require parent UPDATE capability.
                        operation = "update"
                    if operation is not None:
                        return PermissionRequirement.all_of(
                            f"{admin_id}.resources.{resource_id}.{operation}"
                        )
                return requirement
        return access_requirement

    return resolve
