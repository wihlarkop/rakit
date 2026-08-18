# UI-06C Auth & System Surfaces Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give login/session, 403, 404, and production 500 states a coherent minimal Rakit experience while preserving all existing authentication, authorization, CSRF, rate-limit, cookie, mount-path, and generated-API response semantics.

**Architecture:** Introduce one Web-internal auth-reason enum and one Web-only `SystemPageRenderer`. `PrincipalMiddleware` remains responsible for session resolution and only marks a stale-session reason in request state; `AuthorizationMiddleware` remains responsible for gating and accepts a narrow injected browser-forbidden renderer. Starlette exception handlers use the shared renderer for browser 404/500 while generated API paths remain JSON. `base.html` gains explicit `app/auth/system` shell modes while preserving `rakit_shell_enabled` compatibility.

**Tech Stack:** Python 3.12+, Starlette ASGI/raw ASGI middleware, Jinja2, existing Rakit security/session/CSRF/rate-limit services, Tailwind CSS 4.1.18, pytest/pytest-anyio, Ruff, ty.

**Spec:** `docs/superpowers/specs/2026-08-19-ui-06-advanced-operations-auth-system-design.md`

## Global Constraints

- Work from the latest `ui-06-advanced-operations` integration head after UI-06B is merged; implement UI-06C on a child branch.
- Feature/source implementation comes first; regression/security tests are added at the end of the slice.
- Do not rebuild authentication or authorization; presentation sits on the existing security boundary.
- Login CSRF remains the existing pre-session double-submit token. Do not weaken field limits, origin handling, rate limiting, credential normalization, session creation, cookie attributes, or no-store behavior.
- Invalid credentials remain non-enumerating and status 401.
- Rate-limited login remains status 429.
- Logout remains POST-only, validates CSRF when an active session exists, revokes the session, deletes cookies, and redirects with 303.
- Anonymous browser access to a protected route remains a 303 login redirect.
- Anonymous generated API access remains JSON 401.
- Authenticated browser permission failure remains HTTP 403 but becomes system HTML.
- Generated API permission failure remains its existing JSON 403 contract.
- Browser not found remains HTTP 404 HTML only after the existing security boundary permits the request to reach routing.
- Generated API 404 remains JSON.
- Production browser unexpected failure becomes safe HTTP 500 HTML; generated API unexpected failure becomes safe JSON 500 without changing existing expected `RakitError` JSON contracts.
- Debug mode retains Starlette/developer diagnostics rather than the production 500 surface.
- Auth reason query values are fixed whitelist identifiers only. Never render arbitrary query text.
- `session_expired` is emitted only when a prior session cookie was present but became unusable; a normal no-cookie anonymous redirect must not claim expiration.
- 403 must not expose permission identifiers, route names, hidden resource names, or authorization internals.
- 404 must not suggest/enumerate hidden routes/resources.
- 500 must not expose exception strings, traceback, SQL, filesystem paths, storage/database configuration, secrets, or tokens.
- Dashboard/return CTA visibility is permission-aware. System renderers never blindly assume the dashboard is reachable.
- Preserve `rakit_shell_enabled` for custom-template compatibility.
- Reuse `components/theme_control.html`; do not build a second theme system.
- Mounted admin URLs use `mounted_path` / `root_path`, never hardcoded root assumptions.
- No release/tag/PyPI action.

---

## File Map

### Create
- `packages/rakit-web/src/rakit_web/auth_state.py` — Web-internal fixed `AuthReason` enum; no rendering dependency.
- `packages/rakit-web/src/rakit_web/system_responses.py` — safe auth-reason message mapping and browser/API system response helpers.
- `packages/rakit-web/src/rakit_web/templates/system/page.html`
- `packages/rakit-web/src/rakit_web/templates/system/403.html`
- `packages/rakit-web/src/rakit_web/templates/system/404.html`
- `packages/rakit-web/src/rakit_web/templates/system/500.html`
- `packages/rakit-web/tests/test_auth_ui_maturity.py` — slice UI/security regression tests, created after feature work.

### Modify
- `packages/rakit-web/src/rakit_web/templates/base.html` — explicit shell mode and centered auth/system layout.
- `packages/rakit-web/src/rakit_web/templates/auth/login.html` — dedicated auth shell and semantic fixed feedback.
- `packages/rakit-web/src/rakit_web/auth_routes.py` — title/reason presentation and signed-out redirect reason.
- `packages/rakit-web/src/rakit_web/security/authentication.py` — stale-session marker + injected forbidden renderer; security semantics unchanged.
- `packages/rakit-web/src/rakit_web/admin.py` — renderer creation, permission-aware dashboard CTA helper, browser/API exception translation, auth wiring.
- `packages/rakit-web/src/rakit_web/assets/rakit.css`
- `packages/rakit-web/src/rakit_web/static/rakit.css` — generated output.
- `examples/ui_showcase/main.py` only where real auth/system review scenarios need deterministic setup.
- Existing auth/security/API error suites including `test_auth_enforcement.py`, `test_login_security.py`, `test_csrf.py`, `test_generated_rest_http_errors.py`.

---

### Task 1: Add Shared Auth/System Shell Modes

**Files:**
- Modify: `packages/rakit-web/src/rakit_web/templates/base.html`
- Modify: `packages/rakit-web/src/rakit_web/assets/rakit.css`
- Regenerate: `packages/rakit-web/src/rakit_web/static/rakit.css`

**Interfaces:**
- Consumes: existing `rakit_shell_enabled`, optional `rakit_shell_mode`, application title, shared theme control.
- Produces: `app`, `auth`, and `system` presentation contexts.

- [ ] **Step 1: Preserve compatibility and derive shell mode**

Keep:

```jinja
{% set shell_enabled = rakit_shell_enabled | default(true) %}
```

Add:

```jinja
{% set shell_mode = rakit_shell_mode | default('app' if shell_enabled else 'auth') %}
```

Rules:
- `app` keeps current desktop/mobile navigation behavior;
- `auth` and `system` do not render/call the navigation provider;
- existing templates that only pass `rakit_shell_enabled=False` still get a valid no-sidebar shell.

- [ ] **Step 2: Add a minimal non-app header**

For auth/system modes render application title plus existing `components/theme_control.html` using a unique `theme_control_id`. Do not turn the title into a dashboard link unless `dashboard_url` is explicitly supplied and safe.

- [ ] **Step 3: Constrain auth/system content width while preserving shared document behavior**

Keep skip link, announcer, theme initialization, HTMX assets, UI JS, focus target, and semantic background. Use centered constrained content widths for auth/system while app shell retains current width/navigation.

- [ ] **Step 4: Add only reusable CSS, rebuild, verify**

```powershell
bun run css:build
uv run python -c "from rakit_web.resource_routes import build_templates; build_templates(()).env.get_template('base.html')"
uv run ruff format --check .
uv run ruff check .
```

- [ ] **Step 5: Commit**

```powershell
git add packages/rakit-web/src/rakit_web/templates/base.html packages/rakit-web/src/rakit_web/assets/rakit.css packages/rakit-web/src/rakit_web/static/rakit.css
git commit -m "feat(web): add auth and system shell modes"
```

---

### Task 2: Define Fixed Auth Reasons and Safe System Response Rendering

**Files:**
- Create: `packages/rakit-web/src/rakit_web/auth_state.py`
- Create: `packages/rakit-web/src/rakit_web/system_responses.py`
- Create: `packages/rakit-web/src/rakit_web/templates/system/page.html`
- Create: `packages/rakit-web/src/rakit_web/templates/system/403.html`
- Create: `packages/rakit-web/src/rakit_web/templates/system/404.html`
- Create: `packages/rakit-web/src/rakit_web/templates/system/500.html`

**Interfaces:**
- Consumes: Jinja templates, request state/request id, mounted path, fixed public copy.
- Produces: a tiny reason enum, whitelisted login reason presentation, safe browser 403/404/500, and a safe helper for unexpected generated-API 500.

- [ ] **Step 1: Create the rendering-independent reason enum**

`auth_state.py`:

```python
from enum import StrEnum


class AuthReason(StrEnum):
    SESSION_EXPIRED = "session_expired"
    SIGNED_OUT = "signed_out"
```

Keep it Web-internal; do not export it from `rakit`.

- [ ] **Step 2: Map reasons to fixed presentation copy**

In `system_responses.py`:

```python
_AUTH_REASON_MESSAGES = {
    AuthReason.SESSION_EXPIRED: (
        "warning",
        "Your session has expired. Sign in again to continue.",
    ),
    AuthReason.SIGNED_OUT: (
        "success",
        "You have signed out successfully.",
    ),
}


def auth_reason_message(raw: str | None) -> tuple[str, str] | None:
    if raw is None:
        return None
    try:
        reason = AuthReason(raw)
    except ValueError:
        return None
    return _AUTH_REASON_MESSAGES[reason]
```

Never return/render raw query input.

- [ ] **Step 3: Add `SystemPageRenderer` with no exception-text input**

```python
@dataclass(frozen=True, slots=True)
class SystemPageRenderer:
    templates: Jinja2Templates
    label: str

    def forbidden(self, request: Request, *, dashboard_available: bool) -> Response: ...
    def not_found(self, request: Request, *, dashboard_available: bool) -> Response: ...
    def internal_error(self, request: Request, *, dashboard_available: bool) -> Response: ...
```

Each response passes:
- `binding_label=self.label`;
- `rakit_shell_enabled=False`;
- `rakit_shell_mode="system"`;
- exact status 403/404/500;
- `Cache-Control: no-store`;
- `dashboard_url=mounted_path(request, "/")` only when `dashboard_available`;
- request id only on 500 and only when it is a string.

Do not accept an Exception object/message as template context.

- [ ] **Step 4: Add a helper only for unexpected API 500**

```python
def unexpected_api_error(request: Request) -> JSONResponse:
    request_id = request.scope.get("state", {}).get("request_id", "")
    return JSONResponse(
        {
            "error": {
                "code": "internal.error",
                "message": "Internal server error.",
            },
            "request_id": request_id if isinstance(request_id, str) else "",
        },
        status_code=500,
        headers={"Cache-Control": "no-store"},
    )
```

Do not route normal `RakitError` through this helper; preserve existing generated API error contracts.

- [ ] **Step 5: Create safe system templates**

Required public copy:
- 403: `Access denied` / `You don't have permission to view this page.`
- 404: `Page not found` / `The page you're looking for doesn't exist or may have been moved.`
- 500: `Something went wrong` / `We couldn't complete this request.` and request-id support copy when present.

Only show dashboard CTA when `dashboard_url` is non-empty. Baseline 500 has no automatic Retry CTA.

- [ ] **Step 6: Verify and commit**

```powershell
uv run ruff format packages/rakit-web/src/rakit_web/auth_state.py packages/rakit-web/src/rakit_web/system_responses.py
uv run ruff check packages/rakit-web/src/rakit_web/auth_state.py packages/rakit-web/src/rakit_web/system_responses.py
uv run ty check
uv run python -c "from rakit_web.resource_routes import build_templates; t=build_templates(()); [t.env.get_template(p) for p in ('system/403.html','system/404.html','system/500.html')]"
git add packages/rakit-web/src/rakit_web/auth_state.py packages/rakit-web/src/rakit_web/system_responses.py packages/rakit-web/src/rakit_web/templates/system
git commit -m "feat(web): add safe system response surfaces"
```

---

### Task 3: Mature Login and Whitelisted Session Feedback

**Files:**
- Modify: `packages/rakit-web/src/rakit_web/auth_routes.py`
- Modify: `packages/rakit-web/src/rakit_web/templates/auth/login.html`

**Interfaces:**
- Consumes: existing login CSRF behavior, fixed `AuthReason`, safe reason message resolver, application title.
- Produces: dedicated auth shell and fixed session-expired/signed-out feedback with unchanged HTTP/security semantics.

- [ ] **Step 1: Pass application title into auth routes**

Extend `build_auth_routes(..., label: str, ...)` and later pass `self.config.title` from `Admin.asgi()`.

- [ ] **Step 2: Resolve only whitelisted GET reason messages**

Extend `_render_login` context with:

```python
"binding_label": label,
"rakit_shell_enabled": False,
"rakit_shell_mode": "auth",
"reason_message": reason_message,
```

`login_get` calls `auth_reason_message(request.query_params.get("reason"))`. Unknown reason produces `None`; raw query text is never reflected.

- [ ] **Step 3: Keep credential/rate-limit/security failures independent**

POST credential failures remain generic 401, limiter failure remains 429, malformed form / invalid login CSRF retain existing failure semantics. Do not distinguish unknown identifier from wrong password.

- [ ] **Step 4: Add fixed signed-out reason to successful logout redirect**

Build mounted login URL and append only constant `AuthReason.SIGNED_OUT.value`; keep POST, revocation, CSRF logic, cookie deletion, and 303 unchanged.

- [ ] **Step 5: Rewrite login template as minimal auth surface**

Keep hidden login CSRF name/value, Email/Password ids/names/autocomplete/required, and Sign in POST target unchanged. Add semantic reason/error alerts, heading/support copy, full-width CTA. No fake remember-me/reset/social controls.

- [ ] **Step 6: Verify and commit**

```powershell
uv run ruff format packages/rakit-web/src/rakit_web/auth_routes.py
uv run ruff check packages/rakit-web/src/rakit_web/auth_routes.py
uv run ty check
git add packages/rakit-web/src/rakit_web/auth_routes.py packages/rakit-web/src/rakit_web/templates/auth/login.html
git commit -m "feat(web): mature login and session feedback"
```

---

### Task 4: Propagate Session-Expired State Without Changing Authentication Semantics

**Files:**
- Modify: `packages/rakit-web/src/rakit_web/security/authentication.py`

**Interfaces:**
- Consumes: existing `clear_session_cookie` result from `PrincipalMiddleware._resolve()` and `AuthReason` enum only.
- Produces: fixed request-state reason used only on browser login redirect.

- [ ] **Step 1: Add a private state key**

```python
_AUTH_REASON_STATE_KEY = "rakit_auth_reason"
```

- [ ] **Step 2: Mark only stale/unusable-session requests**

After `_resolve()` and state initialization:

```python
if clear_session_cookie:
    scope["state"][_AUTH_REASON_STATE_KEY] = AuthReason.SESSION_EXPIRED.value
```

No-cookie anonymous requests do not get the marker. Keep revoke/cookie-clearing behavior unchanged.

- [ ] **Step 3: Append reason only to browser unauthenticated redirects**

In AuthorizationMiddleware browser redirect logic, append `?reason=session_expired` only when state contains that exact constant. API requests remain JSON 401 and ignore the reason.

- [ ] **Step 4: Smoke-check clean anonymous vs stale session**

Using the showcase/test client:
- clean anonymous protected path -> mounted `/auth/login` without reason;
- stale cookie -> mounted `/auth/login?reason=session_expired` and cookie clear.

- [ ] **Step 5: Commit**

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
- Consumes: exact permission resolver/principal and `SystemPageRenderer.forbidden()`.
- Produces: browser HTML 403 while API 403 remains unchanged JSON.

- [ ] **Step 1: Add a narrow browser forbidden callback type**

```python
BrowserForbiddenRenderer = Callable[[Request, bool], Response]
```

Extend `AuthorizationMiddleware.__init__(..., render_forbidden: BrowserForbiddenRenderer | None = None)`. Do not import Jinja/templates into the security module.

- [ ] **Step 2: Compute dashboard availability with the same permission resolver**

For authenticated browser forbidden state, resolve `requirement_for("/", "GET")`. Dashboard is available only if requirement is absent/public or the current authenticated principal matches it. Do not pass failed requirement/permission details to renderer.

If callback is absent, preserve current plain-text fallback so middleware remains independently usable.

- [ ] **Step 3: Create one shared dashboard availability helper in `Admin.asgi()`**

After `requirement_resolver` exists:

```python
def dashboard_available(request: Request) -> bool:
    requirement = requirement_resolver("/", "GET")
    if requirement is None:
        return True
    principal = request.scope.get("state", {}).get("principal")
    return bool(
        principal is not None
        and principal.authenticated
        and requirement.matches(principal, superuser_bypass=self._superuser_bypass)
    )
```

This helper will also be reused by browser 404/500 rendering.

- [ ] **Step 4: Wire `SystemPageRenderer` into AuthorizationMiddleware**

Create renderer from shared templates/title and pass a callback that renders 403 with the middleware-computed dashboard flag. Keep middleware ordering unchanged: Principal before Authorization, then outer Security and RequestContext.

- [ ] **Step 5: Verify and commit**

```powershell
uv run ruff format packages/rakit-web/src/rakit_web/security/authentication.py packages/rakit-web/src/rakit_web/admin.py
uv run ruff check packages/rakit-web/src/rakit_web/security/authentication.py packages/rakit-web/src/rakit_web/admin.py
uv run ty check
git add packages/rakit-web/src/rakit_web/security/authentication.py packages/rakit-web/src/rakit_web/admin.py
git commit -m "feat(web): render safe browser forbidden pages"
```

---

### Task 6: Add Context-Aware Browser/API 404 and Production 500 Translation

**Files:**
- Modify: `packages/rakit-web/src/rakit_web/admin.py`
- Modify if needed: `packages/rakit-web/src/rakit_web/security/authentication.py`

**Interfaces:**
- Consumes: `admin_relative_path()`, the existing generated-API path rule, shared renderer, permission-aware dashboard helper.
- Produces: browser 404/500 HTML and generated API JSON while preserving existing expected error contracts.

- [ ] **Step 1: Reuse one authoritative generated-API path classifier**

Expose/reuse a Web-internal helper matching the current rule:

```python
def is_generated_api_path(path: str) -> bool:
    return path == "/api" or path.startswith("/api/")
```

Use it in both security and exception translation. Do not infer from Accept alone.

- [ ] **Step 2: Refactor `http_error_handler`**

Use `relative_path = admin_relative_path(request)`.

Generated API keeps existing HTTPException JSON shape/codes (`http.not_found`, `http.method_not_allowed`, `http.error`) plus request id/no-store.

Browser:
- 404 -> `system_renderer.not_found(request, dashboard_available=dashboard_available(request))`;
- other HTTPException statuses retain their existing safe/route-specific response unless explicitly owned by this slice.

- [ ] **Step 3: Refactor `rakit_error_handler` without changing generated API payload contracts**

For generated API path, continue returning `exc.to_public_dict()` with exact `exc.status_code` and no-store as today.

For browser path:
- status 404 -> system 404;
- status 403 -> system 403 without permission details;
- other expected 4xx retain safe existing browser/route-specific behavior;
- status >=500 with `debug=False` -> generic system 500 and **never** `exc.message`.

- [ ] **Step 4: Add an unexpected exception handler for production**

```python
async def unexpected_error_handler(request: Request, exc: Exception) -> Response:
    del exc
    if is_generated_api_path(admin_relative_path(request)):
        return unexpected_api_error(request)
    return system_renderer.internal_error(
        request,
        dashboard_available=dashboard_available(request),
    )
```

Register `Exception: unexpected_error_handler` alongside existing handlers. Keep `Starlette(debug=self.config.debug)`; verify debug mode still uses developer diagnostics rather than production system 500.

- [ ] **Step 5: Pass `label=self.config.title` to `build_auth_routes`**

Complete Task 3 signature wiring.

- [ ] **Step 6: Keep 404 security ordering unchanged**

Do not change requirement resolver fallback. Unknown protected paths still pass through auth/admin permission gating before Starlette routing:
- anonymous -> 303 login;
- authenticated without admin access -> 403;
- authenticated with access -> HTML 404.

- [ ] **Step 7: Manual production leakage smoke**

Use `debug=False` fixture with an exception containing seeded credentials/path text. Browser response must be generic 500 + request id; API response safe JSON 500. Seeded string must be absent.

- [ ] **Step 8: Commit**

```powershell
git add packages/rakit-web/src/rakit_web/admin.py packages/rakit-web/src/rakit_web/security/authentication.py
git commit -m "feat(web): add safe browser system error translation"
```

Only stage authentication.py if the shared API classifier was moved/changed there.

---

### Task 7: Exercise Auth/System Surfaces in `examples/ui_showcase`

**Files:**
- Modify: `examples/ui_showcase/main.py` only if deterministic real-runtime scenarios need setup.

**Interfaces:**
- Consumes: real Admin/auth/error behavior.
- Produces: repeatable visual acceptance without fake standalone system templates.

- [ ] **Step 1: Use real login flow**

Review normal login, invalid credentials, signed-out redirect, and session expiration by invalidating a real demo session record. Rate-limit state may be tested in automated fixture if making it deterministic in the showcase would degrade the demo.

- [ ] **Step 2: Use real AuthorizationMiddleware for 403**

Add/use a restricted principal/page only if needed; never create a fake 403 page route.

- [ ] **Step 3: Use a truly missing route for 404**

Authenticated permitted user visits `/this-route-does-not-exist`; clean anonymous request to same path must redirect to login instead of seeing informative 404.

- [ ] **Step 4: Keep production 500 primarily in test fixture**

The showcase runs `debug=True`; do not weaken that to display the pretty 500. Use automated `debug=False` fixture as primary 500 evidence.

- [ ] **Step 5: Browser review**

```powershell
uv run python -m examples.ui_showcase.main
```

Review login/403/404 in Light/Dark and narrow/desktop widths; confirm no sidebar and working theme control.

- [ ] **Step 6: Commit only actual showcase changes**

```powershell
git add examples/ui_showcase/main.py
git commit -m "feat(examples): cover auth and system surfaces"
```

Skip commit if no showcase source change was necessary.

---

### Task 8: Add Security/UI Regression Tests Last and Run the UI-06C Gate

**Files:**
- Create: `packages/rakit-web/tests/test_auth_ui_maturity.py`
- Modify existing auth/security/API error suites only if new presentation assertions require it.

**Interfaces:**
- Consumes: completed UI-06C behavior.
- Produces: security, response-format, leakage, shell, and mount regression coverage.

- [ ] **Step 1: Test auth reason whitelist/non-reflection**

Unknown arbitrary reason resolves to `None`; request with encoded HTML/script reason never reflects that raw value.

- [ ] **Step 2: Test stale-session vs clean-anonymous redirects**

Assert clean anonymous protected browser route redirects to mounted login without reason; stale session redirects to `?reason=session_expired` and clears cookie; stale API request remains JSON 401.

- [ ] **Step 3: Reassert login/logout security semantics**

Unknown identifier/wrong password produce identical generic 401 behavior; rate-limit remains 429; invalid login CSRF remains 403 and does not call credential backend; logout remains POST + active-session CSRF + revoke/delete-cookie + 303 signed-out reason.

- [ ] **Step 4: Test browser/API 403 matrix**

Browser forbidden = HTML 403 with `Access denied`, no permission ids. API forbidden remains existing JSON `auth.forbidden` contract.

- [ ] **Step 5: Test 404 security ordering and mounted paths**

Matrix:
- anonymous missing path -> 303 login;
- authenticated without admin access -> 403;
- authenticated with admin access -> HTML 404;
- mounted admin dashboard CTA points to mounted root;
- `/api/missing` after applicable auth -> JSON 404.

No route/resource registry disclosure.

- [ ] **Step 6: Test production 500 leakage boundary**

Raise `RuntimeError("postgresql://user:secret@db/private + /srv/app/internal.py")` under `debug=False`. Browser response is generic HTML 500 + request id with all seeded secret/path text absent. Generated API unexpected failure is safe JSON with code `internal.error` and request id. Under `debug=True`, response is not the production system-page copy.

- [ ] **Step 7: Test shell markup**

Login/403/404/500 contain theme controls and do not contain desktop/mobile admin navigation. Dashboard CTA appears only when permission-aware flag permits it.

- [ ] **Step 8: Run the exact focused suite**

```powershell
uv run pytest packages/rakit-web/tests/test_auth_ui_maturity.py packages/rakit-web/tests/test_auth_enforcement.py packages/rakit-web/tests/test_login_security.py packages/rakit-web/tests/test_csrf.py packages/rakit-web/tests/test_generated_rest_http_errors.py -q
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
git add packages/rakit-web/tests/test_auth_ui_maturity.py packages/rakit-web/tests/test_auth_enforcement.py packages/rakit-web/tests/test_login_security.py packages/rakit-web/tests/test_csrf.py packages/rakit-web/tests/test_generated_rest_http_errors.py
git commit -m "test(web): cover auth and system UI boundaries"
```

Only stage existing files that actually changed.

- [ ] **Step 11: Open UI-06C PR against `ui-06-advanced-operations`**

Require fresh PR CI and maintainer browser acceptance for login/session/403/404/themes plus production-500 automated evidence. Merge only into integration.
