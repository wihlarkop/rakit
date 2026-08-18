# UI-06C Auth & System Surfaces Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give login/session, 403, 404, and production 500 states a coherent minimal Rakit experience while preserving all existing authentication, authorization, CSRF, rate-limit, cookie, mount-path, and generated-API response semantics.

**Architecture:** Introduce one Web-only `SystemPageRenderer` shared by auth/system templates and error translation. Keep `PrincipalMiddleware` responsible for session resolution and `AuthorizationMiddleware` responsible for gating; add only a safe request-state auth-reason marker and an injected browser-forbidden renderer. Starlette exception handlers use the same renderer for browser 404/500 while generated API paths remain JSON. `base.html` gains explicit `app/auth/system` shell modes while preserving `rakit_shell_enabled` compatibility.

**Tech Stack:** Python 3.12+, Starlette ASGI/raw ASGI middleware, Jinja2, existing Rakit security middleware/session/CSRF/rate limiting, Tailwind CSS 4.1.18, pytest/pytest-anyio, Ruff, ty.

**Spec:** `docs/superpowers/specs/2026-08-19-ui-06-advanced-operations-auth-system-design.md`

## Global Constraints

- Work from the latest `ui-06-advanced-operations` integration head after UI-06B is merged; implement UI-06C on a child branch.
- Feature/source implementation comes first; regression/security tests are added at the end of the slice.
- Do not rebuild authentication or authorization; presentation must sit on the existing security boundary.
- Login CSRF remains the existing pre-session double-submit token. Do not weaken field limits, origin handling, rate limiting, credential normalization, session creation, cookie attributes, or no-store behavior.
- Invalid credentials remain non-enumerating and status 401.
- Rate-limited login remains status 429.
- Logout remains POST-only, CSRF-protected when an active session exists, revokes the session, deletes cookies, and redirects with 303.
- Anonymous browser access to a protected route remains a 303 login redirect.
- Anonymous generated API access remains JSON 401.
- Authenticated browser permission failure remains HTTP 403 but becomes system HTML.
- Generated API permission failure remains JSON 403.
- Browser not found remains HTTP 404 HTML only after the existing security boundary permits the request to reach routing.
- Generated API 404 remains JSON.
- Production browser unexpected failure becomes safe HTTP 500 HTML; generated API 500 remains safe JSON.
- Debug mode retains Starlette/developer diagnostics rather than the production 500 surface.
- Auth reason query values are fixed whitelist identifiers only. Never render arbitrary query text.
- `session_expired` is emitted only when a prior session cookie was present but became unusable; a normal no-cookie anonymous redirect must not claim expiration.
- 403 must not expose permission identifiers, route names, hidden resource names, or authorization internals.
- 404 must not suggest/enumerate hidden routes/resources.
- 500 must not expose exception strings, traceback, SQL, filesystem paths, storage/database configuration, secrets, or tokens.
- Preserve `rakit_shell_enabled` for custom-template compatibility.
- Reuse `components/theme_control.html`; do not build a second theme system.
- Mounted admin URLs must use `mounted_path` / `root_path`, never hardcoded root assumptions.
- No release/tag/PyPI action.

---

## File Map

### Create
- `packages/rakit-web/src/rakit_web/system_responses.py` — safe browser/API system response renderer and fixed auth-reason mapping.
- `packages/rakit-web/src/rakit_web/templates/system/page.html` — shared minimal system shell content.
- `packages/rakit-web/src/rakit_web/templates/system/403.html`
- `packages/rakit-web/src/rakit_web/templates/system/404.html`
- `packages/rakit-web/src/rakit_web/templates/system/500.html`
- `packages/rakit-web/tests/test_auth_ui_maturity.py` — slice UI/security regression tests, created after feature work.

### Modify
- `packages/rakit-web/src/rakit_web/templates/base.html` — explicit shell mode and centered auth/system layout while preserving existing app shell.
- `packages/rakit-web/src/rakit_web/templates/auth/login.html` — dedicated auth shell, fixed reason feedback, semantic errors.
- `packages/rakit-web/src/rakit_web/auth_routes.py` — pass title and whitelisted reason presentation; signed-out redirect reason.
- `packages/rakit-web/src/rakit_web/security/authentication.py` — stale-session marker + injected forbidden renderer; auth/API semantics remain unchanged.
- `packages/rakit-web/src/rakit_web/admin.py` — create renderer; browser/API exception translation; wire auth/system callbacks and title.
- `packages/rakit-web/src/rakit_web/assets/rakit.css`
- `packages/rakit-web/src/rakit_web/static/rakit.css` — generated output.
- `examples/ui_showcase/main.py` — deterministic auth/system states where practical.
- Existing auth/security suites, especially `packages/rakit-web/tests/test_auth_enforcement.py`, `test_csrf.py`, and mounted-admin/runtime tests.

---

### Task 1: Add Shared Auth/System Shell Modes

**Files:**
- Modify: `packages/rakit-web/src/rakit_web/templates/base.html`
- Modify: `packages/rakit-web/src/rakit_web/assets/rakit.css`
- Regenerate: `packages/rakit-web/src/rakit_web/static/rakit.css`

**Interfaces:**
- Consumes: existing `rakit_shell_enabled`, optional new `rakit_shell_mode`, `binding_label`/title, shared theme control.
- Produces: three presentation modes: `app`, `auth`, `system`.

- [ ] **Step 1: Preserve the existing compatibility flag and derive shell mode**

At the top of `<body>` rendering, keep:

```jinja
{% set shell_enabled = rakit_shell_enabled | default(true) %}
```

and add:

```jinja
{% set shell_mode = rakit_shell_mode | default('app' if shell_enabled else 'auth') %}
```

Rules:
- `app` uses the current navigation/sidebar/mobile shell unchanged;
- `auth` and `system` must not call/render the navigation provider;
- existing templates that only pass `rakit_shell_enabled=False` continue to receive an auth-like no-sidebar layout.

- [ ] **Step 2: Add a minimal non-app header for auth/system modes**

For `shell_mode in ('auth', 'system')`, render a small top bar containing:
- application title from `binding_label | default('Rakit')`;
- an `Admin` badge only if it remains visually useful and non-sensitive;
- existing `components/theme_control.html` with a unique `theme_control_id` such as `rakit-theme-system`;
- no sidebar/resource navigation.

Use mounted-safe dashboard links only when the template explicitly receives `dashboard_url`; the shell title itself should not become a blind link.

- [ ] **Step 3: Add constrained main widths by shell mode**

Keep current `max-w-7xl` for app. Use a centered constrained width for auth/system, e.g. `max-w-md` for login and `max-w-xl` for system pages. Keep skip link, announcer, main focus target, theme scripts, HTMX assets, and UI JS shared.

- [ ] **Step 4: Add only stable shell CSS primitives if template utilities become repetitive**

Prefer direct Tailwind utilities. Add `.rakit-auth-surface` / `.rakit-system-surface` only if used across multiple templates.

- [ ] **Step 5: Rebuild and load templates**

```powershell
bun run css:build
uv run python -c "from rakit_web.resource_routes import build_templates; build_templates(()).env.get_template('base.html')"
uv run ruff format --check .
uv run ruff check .
```

- [ ] **Step 6: Commit shell modes**

```powershell
git add packages/rakit-web/src/rakit_web/templates/base.html packages/rakit-web/src/rakit_web/assets/rakit.css packages/rakit-web/src/rakit_web/static/rakit.css
git commit -m "feat(web): add auth and system shell modes"
```

---

### Task 2: Build the Safe System Response Renderer

**Files:**
- Create: `packages/rakit-web/src/rakit_web/system_responses.py`
- Create: `packages/rakit-web/src/rakit_web/templates/system/page.html`
- Create: `packages/rakit-web/src/rakit_web/templates/system/403.html`
- Create: `packages/rakit-web/src/rakit_web/templates/system/404.html`
- Create: `packages/rakit-web/src/rakit_web/templates/system/500.html`

**Interfaces:**
- Consumes: `Jinja2Templates`, request state/request id, mounted path, fixed public messages.
- Produces: safe browser 403/404/500 responses plus API error helper with stable JSON envelope.

- [ ] **Step 1: Define fixed safe messages and auth reasons**

In `system_responses.py`:

```python
from enum import StrEnum


class AuthReason(StrEnum):
    SESSION_EXPIRED = "session_expired"
    SIGNED_OUT = "signed_out"


_AUTH_REASON_MESSAGES = {
    AuthReason.SESSION_EXPIRED: ("warning", "Your session has expired. Sign in again to continue."),
    AuthReason.SIGNED_OUT: ("success", "You have signed out successfully."),
}
```

Add:

```python
def auth_reason_message(raw: str | None) -> tuple[str, str] | None:
    try:
        reason = AuthReason(raw) if raw is not None else None
    except ValueError:
        return None
    return _AUTH_REASON_MESSAGES.get(reason) if reason is not None else None
```

Never return the original `raw` text.

- [ ] **Step 2: Add `SystemPageRenderer`**

Use an immutable binding-like object:

```python
@dataclass(frozen=True, slots=True)
class SystemPageRenderer:
    templates: Jinja2Templates
    label: str

    def forbidden(self, request: Request, *, dashboard_available: bool) -> Response: ...
    def not_found(self, request: Request, *, dashboard_available: bool) -> Response: ...
    def internal_error(self, request: Request, *, dashboard_available: bool) -> Response: ...
```

Each method calls `TemplateResponse` with:
- `binding_label=self.label`;
- `rakit_shell_enabled=False`;
- `rakit_shell_mode="system"`;
- `status_code` 403/404/500;
- `Cache-Control: no-store`;
- `dashboard_url=mounted_path(request, "/") if dashboard_available else ""`;
- request id only for 500 and only if it is a string.

Do **not** accept exception text as a template argument.

- [ ] **Step 3: Add a shared API system-error helper**

Create:

```python
def api_error_response(
    request: Request,
    *,
    status_code: int,
    code: str,
    message: str,
    headers: Mapping[str, str] | None = None,
) -> JSONResponse:
    ...
```

It uses the existing envelope:

```json
{
  "error": {"code": "...", "message": "..."},
  "request_id": "..."
}
```

This helper must receive only explicitly safe public messages from callers.

- [ ] **Step 4: Create the three system templates**

Use `system/page.html` as the shared structure or include base macros. Required copy:
- 403: heading `Access denied`, body `You don't have permission to view this page.`;
- 404: heading `Page not found`, body `The page you're looking for doesn't exist or may have been moved.`;
- 500: heading `Something went wrong`, body `We couldn't complete this request.` plus request-id support copy when present.

Only show `Back to dashboard` when `dashboard_url` is non-empty.

For 500, do not include a Retry link in the shared template yet. Add it only if a caller explicitly passes a safe `retry_url` for GET/HEAD; the baseline renderer should be conservative.

- [ ] **Step 5: Structural verification**

```powershell
uv run ruff format packages/rakit-web/src/rakit_web/system_responses.py
uv run ruff check packages/rakit-web/src/rakit_web/system_responses.py
uv run ty check
uv run python -c "from rakit_web.resource_routes import build_templates; t=build_templates(()); [t.env.get_template(p) for p in ('system/403.html','system/404.html','system/500.html')]"
```

- [ ] **Step 6: Commit renderer/templates**

```powershell
git add packages/rakit-web/src/rakit_web/system_responses.py packages/rakit-web/src/rakit_web/templates/system
git commit -m "feat(web): add safe system response surfaces"
```

---

### Task 3: Mature Login and Whitelisted Session Feedback

**Files:**
- Modify: `packages/rakit-web/src/rakit_web/auth_routes.py`
- Modify: `packages/rakit-web/src/rakit_web/templates/auth/login.html`

**Interfaces:**
- Consumes: existing login CSRF cookie/form, `AuthReason` whitelist, admin title.
- Produces: dedicated auth shell, fixed session-expired/signed-out feedback, same status/security semantics.

- [ ] **Step 1: Pass the application title into auth routes**

Extend:

```python
def build_auth_routes(
    *,
    ...,
    admin_id: str,
    label: str,
    secure_cookies: bool,
    ...,
) -> list[Route]:
```

`Admin.asgi()` will pass `label=self.config.title` later.

- [ ] **Step 2: Resolve only whitelisted reason messages on login GET**

Change `_render_login` to accept an optional `reason_message: tuple[str, str] | None`. Add template context:

```python
"binding_label": label,
"rakit_shell_enabled": False,
"rakit_shell_mode": "auth",
"reason_message": reason_message,
```

`login_get` resolves:

```python
reason_message = auth_reason_message(request.query_params.get("reason"))
return _render_login(request, error=None, reason_message=reason_message)
```

If the query parameter is unknown, `reason_message` is `None`. Do not reflect the query string.

- [ ] **Step 3: Keep credential/rate-limit errors independent from reason messages**

POST error renders may omit stale GET reason state. Continue exact backend copy/status:
- invalid credentials => 401;
- rate-limit => 429;
- malformed login / invalid CSRF retain current failure response semantics.

Do not change identifier/password error distinction.

- [ ] **Step 4: Add signed-out reason to successful logout redirect**

Use a mounted-safe URL:

```python
login_url = mounted_path(request, "/auth/login")
response = RedirectResponse(
    url=f"{login_url}?reason={AuthReason.SIGNED_OUT.value}",
    status_code=303,
)
```

Because the reason is a constant enum value, no arbitrary query encoding is needed; using `urlencode` is also acceptable.

Keep session/CSRF cookie deletion exactly as today.

- [ ] **Step 5: Rewrite `auth/login.html` as the minimal auth surface**

Required structure:
- `{% extends "base.html" %}`;
- concise `Welcome back` heading;
- support copy using `binding_label`;
- `reason_message` rendered as semantic success/warning alert based only on its fixed kind;
- `error` rendered as `rakit-alert rakit-alert-danger` with `role="alert"`;
- hidden `login_csrf_token` field unchanged;
- Email and Password labels/IDs/names/autocomplete/required unchanged;
- full-width primary Sign in button;
- no fake remember-me/password-reset/social-auth controls.

- [ ] **Step 6: Run structural verification**

```powershell
uv run ruff format packages/rakit-web/src/rakit_web/auth_routes.py
uv run ruff check packages/rakit-web/src/rakit_web/auth_routes.py
uv run ty check
```

- [ ] **Step 7: Commit auth UI**

```powershell
git add packages/rakit-web/src/rakit_web/auth_routes.py packages/rakit-web/src/rakit_web/templates/auth/login.html
git commit -m "feat(web): mature login and session feedback"
```

---

### Task 4: Propagate Session-Expired State Without Changing Authentication Semantics

**Files:**
- Modify: `packages/rakit-web/src/rakit_web/security/authentication.py`

**Interfaces:**
- Consumes: existing `clear_session_cookie` result from `PrincipalMiddleware._resolve()`.
- Produces: a fixed request-state reason used only when AuthorizationMiddleware performs a browser login redirect.

- [ ] **Step 1: Add a private request-state key**

Use a module constant:

```python
_AUTH_REASON_STATE_KEY = "rakit_auth_reason"
```

Do not expose it as public user input.

- [ ] **Step 2: Mark only stale/unusable-session requests**

After `_resolve()` returns and `scope["state"]` is initialized:

```python
if clear_session_cookie:
    scope["state"][_AUTH_REASON_STATE_KEY] = AuthReason.SESSION_EXPIRED.value
```

This condition already means a session cookie was present but no longer usable. No-cookie anonymous requests leave the key absent.

Keep session revocation and cookie-clearing behavior unchanged.

- [ ] **Step 3: Add reason only to browser auth redirect**

In the unauthenticated browser branch of `AuthorizationMiddleware`:

```python
login_url = mounted_path(request, LOGIN_PATH)
reason = scope.get("state", {}).get(_AUTH_REASON_STATE_KEY)
if reason == AuthReason.SESSION_EXPIRED.value:
    login_url = f"{login_url}?reason={AuthReason.SESSION_EXPIRED.value}"
```

Then use the same 303 + `Cache-Control: no-store` RedirectResponse.

API requests ignore the reason and remain JSON 401.

- [ ] **Step 4: Verify no-cookie behavior manually with a tiny ASGI smoke**

Run the existing auth test helper or a local one-off request through the showcase:

```powershell
uv run python -m examples.ui_showcase.main
```

Check:
- clean anonymous visit to a protected path -> `/auth/login` without reason;
- stale cookie -> `/auth/login?reason=session_expired` and cookie deletion.

- [ ] **Step 5: Commit stale-session signaling**

```powershell
git add packages/rakit-web/src/rakit_web/security/authentication.py
git commit -m "feat(web): surface expired session redirects safely"
```

---

### Task 5: Render Browser 403 Through an Injected Callback

**Files:**
- Modify: `packages/rakit-web/src/rakit_web/security/authentication.py`
- Modify: `packages/rakit-web/src/rakit_web/admin.py`

**Interfaces:**
- Consumes: exact permission resolver/principal, `SystemPageRenderer.forbidden()`.
- Produces: browser 403 HTML while API 403 stays unchanged JSON.

- [ ] **Step 1: Add a narrow browser forbidden renderer type**

In `security/authentication.py`:

```python
BrowserForbiddenRenderer = Callable[[Request, bool], Response]
```

Extend `AuthorizationMiddleware.__init__`:

```python
render_forbidden: BrowserForbiddenRenderer | None = None
```

Do not import templates into the security module.

- [ ] **Step 2: Determine whether dashboard is safe using the same resolver**

In the authenticated-forbidden browser branch:

```python
dashboard_requirement = self._requirement_for("/", "GET")
dashboard_available = (
    dashboard_requirement is None
    or dashboard_requirement.matches(principal, superuser_bypass=self._superuser_bypass)
)
```

If `render_forbidden` exists, call it with `(request, dashboard_available)`; otherwise preserve the current PlainText fallback. This makes the middleware reusable outside the full Admin facade.

Do not pass the failed requirement or permission names to the renderer.

- [ ] **Step 3: Wire the renderer in `Admin.asgi()`**

After `templates = build_templates(...)`, create:

```python
system_renderer = SystemPageRenderer(templates=templates, label=self.config.title)
```

When creating `AuthorizationMiddleware`:

```python
render_forbidden=lambda request, dashboard_available: system_renderer.forbidden(
    request,
    dashboard_available=dashboard_available,
),
```

Keep middleware ordering unchanged: Principal resolves before Authorization reads principal; Security and RequestContext remain outer wrappers.

- [ ] **Step 4: Run type/static verification**

```powershell
uv run ruff format packages/rakit-web/src/rakit_web/security/authentication.py packages/rakit-web/src/rakit_web/admin.py
uv run ruff check packages/rakit-web/src/rakit_web/security/authentication.py packages/rakit-web/src/rakit_web/admin.py
uv run ty check
```

- [ ] **Step 5: Commit 403 presentation wiring**

```powershell
git add packages/rakit-web/src/rakit_web/security/authentication.py packages/rakit-web/src/rakit_web/admin.py
git commit -m "feat(web): render safe browser forbidden pages"
```

---

### Task 6: Add Context-Aware Browser/API 404 and 500 Translation

**Files:**
- Modify: `packages/rakit-web/src/rakit_web/admin.py`
- Modify if needed: `packages/rakit-web/src/rakit_web/system_responses.py`

**Interfaces:**
- Consumes: `admin_relative_path()`, existing `_is_generated_api_path` behavior or equivalent helper, `SystemPageRenderer`.
- Produces: browser 404/500 HTML and generated API JSON without changing status/error meaning.

- [ ] **Step 1: Use one authoritative API-path classifier**

Promote the existing private `_is_generated_api_path` to a reusable Web-internal helper, e.g.:

```python
def is_generated_api_path(path: str) -> bool:
    return path == "/api" or path.startswith("/api/")
```

Update existing security use to that helper. Do not infer API solely from `Accept`.

- [ ] **Step 2: Refactor `http_error_handler`**

Use `relative_path = admin_relative_path(request)`.

For generated API:
- 404 => `http.not_found` JSON;
- 405 => `http.method_not_allowed` JSON;
- other HTTPException => `http.error` JSON;
- preserve `exc.headers` plus no-store.

For browser:
- 404 => `system_renderer.not_found(request, dashboard_available=True)` **only because the request has already passed middleware authorization to reach Starlette routing**;
- other HTTPException statuses keep an appropriate existing safe response unless separately owned by UI-06C. Do not silently convert all 4xx into 404/500 pages.

- [ ] **Step 3: Refactor `rakit_error_handler` by browser/API context**

Generated API path: keep `exc.to_public_dict()` JSON and exact `exc.status_code`.

Browser path:
- `exc.status_code == 404` => safe system 404;
- `exc.status_code == 403` => safe system 403 without permission details;
- other expected 4xx keep a safe existing browser response or route-specific presentation;
- 5xx must not render `exc.message`; use the generic production 500 surface when `debug=False`.

- [ ] **Step 4: Add a generic unexpected exception handler**

Define:

```python
async def unexpected_error_handler(request: Request, exc: Exception) -> Response:
    del exc
    relative_path = admin_relative_path(request)
    if is_generated_api_path(relative_path):
        return api_error_response(
            request,
            status_code=500,
            code="internal_error",
            message="Internal server error.",
        )
    return system_renderer.internal_error(request, dashboard_available=True)
```

Register it in Starlette:

```python
exception_handlers={
    RakitError: rakit_error_handler,
    HTTPException: http_error_handler,
    Exception: unexpected_error_handler,
}
```

Keep `debug=self.config.debug`. Starlette debug behavior must remain authoritative; verify in tests that debug exceptions are not replaced by the production 500 template.

- [ ] **Step 5: Pass `label=self.config.title` to `build_auth_routes`**

Wire the signature change from Task 3.

- [ ] **Step 6: Keep 404 security ordering unchanged**

Do not change `build_requirement_resolver` fallback behavior. Unknown non-public paths still require admin access before routing, so:
- anonymous unknown path -> 303 login;
- authenticated without admin access -> 403;
- authenticated with access -> routed 404 HTML.

- [ ] **Step 7: Verify production output manually**

With `debug=False` test app/showcase variant:
- route raising `RuntimeError("SECRET_DB_PASSWORD=...")` renders generic 500 without string;
- request id appears when RequestContext assigned one;
- `/api/...` equivalent failure is JSON.

- [ ] **Step 8: Commit error translation**

```powershell
git add packages/rakit-web/src/rakit_web/admin.py packages/rakit-web/src/rakit_web/system_responses.py
git commit -m "feat(web): add safe browser system error translation"
```

---

### Task 7: Exercise Auth/System Surfaces in `examples/ui_showcase`

**Files:**
- Modify: `examples/ui_showcase/main.py`
- Add development-only route/page hooks only if needed to make deterministic 403/404/500 review practical.

**Interfaces:**
- Consumes: normal public Admin/auth configuration and framework-owned error behavior.
- Produces: repeatable visual acceptance scenarios.

- [ ] **Step 1: Keep real login flow as the primary auth acceptance path**

Use existing showcase credentials. Review:
- login initial state;
- invalid credentials 401;
- rate-limit state if the demo limiter can deterministically reach it without making the app inconvenient;
- signed-out message through real logout POST;
- session-expired message by invalidating a demo session record, not by hand-building HTML.

- [ ] **Step 2: Add a deterministic restricted page/resource if needed for 403**

Use a principal/permission scenario that reaches the real AuthorizationMiddleware. Do not create a custom template pretending to be 403.

- [ ] **Step 3: Use a truly missing route for 404**

Review `/this-route-does-not-exist` while authenticated with admin access. Also confirm anonymous request is redirected to login rather than receiving informative 404.

- [ ] **Step 4: Add a development-only error trigger for production-500 visual QA if practical**

Because the normal showcase runs `debug=True`, a separate test fixture is preferred for safe production 500 verification. Do not weaken debug behavior just to show the pretty 500 in the showcase.

- [ ] **Step 5: Browser review**

```powershell
uv run python -m examples.ui_showcase.main
```

Review Login/403/404 in Light and Dark, desktop and narrow viewport. Verify system pages have no sidebar and theme control still works.

- [ ] **Step 6: Commit showcase-only scenario changes**

```powershell
git add examples/ui_showcase/main.py
git commit -m "feat(examples): cover auth and system surfaces"
```

Skip this commit if no showcase code change was needed; tests may provide the production-500 fixture.

---

### Task 8: Add Security/UI Regression Tests Last and Run the UI-06C Gate

**Files:**
- Create: `packages/rakit-web/tests/test_auth_ui_maturity.py`
- Modify existing auth/security tests only where new response presentation requires assertions.

**Interfaces:**
- Consumes: completed UI-06C behavior.
- Produces: security and HTTP-format regression coverage.

- [ ] **Step 1: Test auth reason whitelist**

```python
def test_unknown_auth_reason_is_not_reflected() -> None:
    assert auth_reason_message("<script>alert(1)</script>") is None
```

Request `/auth/login?reason=<encoded-arbitrary-value>` and assert the raw value is absent from the response.

- [ ] **Step 2: Test stale-session vs clean-anonymous redirects**

Assert:
- no session cookie + protected browser route => 303 to mounted `/auth/login` with no reason;
- stale session cookie => 303 to `?reason=session_expired` and session-cookie deletion header;
- API stale session => JSON 401, not HTML/login redirect.

- [ ] **Step 3: Reassert login security semantics**

Cover:
- unknown identifier and wrong password return the same generic UI copy/status 401;
- rate-limit remains 429;
- invalid login CSRF stays 403 and credentials backend is not invoked;
- logout still requires POST and validates CSRF for active session;
- successful logout redirects 303 to whitelisted `signed_out` reason and deletes session/CSRF cookies.

- [ ] **Step 4: Test browser/API 403 matrix**

Browser authenticated without permission:

```python
assert response.status_code == 403
assert response.headers["content-type"].startswith("text/html")
assert "Access denied" in response.text
assert "ops.resources.secret.read" not in response.text
```

API forbidden:

```python
assert response.status_code == 403
assert response.headers["content-type"].startswith("application/json")
assert response.json()["error"]["code"] == "auth.forbidden"
```

- [ ] **Step 5: Test 404 security ordering and mounted paths**

Matrix:
- anonymous `/missing` => 303 login;
- authenticated without admin access `/missing` => 403;
- authenticated with admin access `/missing` => HTML 404;
- mounted admin `/admin/missing` dashboard CTA points to `/admin/`, never `/`;
- `/api/missing` after appropriate auth => JSON 404.

Assert response does not contain known hidden resource names/registered route dumps.

- [ ] **Step 6: Test production 500 leakage boundary**

Create a route/handler that raises:

```python
RuntimeError("postgresql://user:secret@db/private + /srv/app/internal.py")
```

For `debug=False` browser request assert:
- 500 HTML;
- `Something went wrong` present;
- request id present when assigned;
- the exception string, `secret`, `/srv/app/internal.py`, traceback markers absent.

For generated API failure assert safe JSON 500 + request id and no exception string.

For `debug=True`, assert the response is not the production `Something went wrong` system page; developer diagnostic behavior remains enabled.

- [ ] **Step 7: Test auth/system shell markup**

Assert login/403/404/500 HTML contains `data-theme` controls / `data-rakit-theme-control` and does **not** contain `data-rakit-desktop-navigation` or mobile admin navigation.

- [ ] **Step 8: Run focused tests**

```powershell
uv run pytest packages/rakit-web/tests/test_auth_ui_maturity.py packages/rakit-web/tests/test_auth_enforcement.py packages/rakit-web/tests/test_csrf.py -q
```

Expected: PASS.

- [ ] **Step 9: Run full PR gate locally**

```powershell
bun run css:build
uv run ruff format --check .
uv run ruff check .
uv run ty check
uv run pytest
uv run mkdocs build --strict
uv run python scripts/check_artifacts.py
git status --short
```

- [ ] **Step 10: Commit tests**

```powershell
git add packages/rakit-web/tests/test_auth_ui_maturity.py packages/rakit-web/tests/test_auth_enforcement.py packages/rakit-web/tests/test_csrf.py
git commit -m "test(web): cover auth and system UI boundaries"
```

Only stage existing auth/security test files if they actually changed.

- [ ] **Step 11: Open the UI-06C PR against `ui-06-advanced-operations`**

Require fresh PR CI and maintainer browser acceptance for login, session feedback, 403, 404, Light/Dark, and production-500 test evidence. Merge only into the integration branch.
