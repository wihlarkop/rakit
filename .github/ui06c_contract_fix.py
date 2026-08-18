from pathlib import Path


def replace_once(path: Path, old: str, new: str) -> None:
    text = path.read_text()
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"expected one match in {path}: {old[:100]!r}; got {count}")
    path.write_text(text.replace(old, new, 1))


system = Path("packages/rakit-web/src/rakit_web/system_responses.py")
replace_once(system, "from .auth_state import AuthReason\n", "from ._paths import mounted_path\nfrom .auth_state import AuthReason\n")
replace_once(
    system,
    '''        dashboard_url: str | None = None,\n        request_id: str | None = None,\n    ) -> Response:\n        return self.templates.TemplateResponse(\n            request,\n            template,\n            {\n                "label": self.label,\n                "system_title": title,\n                "system_message": message,\n                "dashboard_url": dashboard_url,\n''',
    '''        dashboard_available: bool,\n        request_id: str | None = None,\n    ) -> Response:\n        return self.templates.TemplateResponse(\n            request,\n            template,\n            {\n                "binding_label": self.label,\n                "system_title": title,\n                "system_message": message,\n                "dashboard_url": mounted_path(request, "/") if dashboard_available else None,\n''',
)
replace_once(
    system,
    '''    def forbidden(self, request: Request, *, dashboard_url: str | None = None) -> Response:\n''',
    '''    def forbidden(self, request: Request, *, dashboard_available: bool) -> Response:\n''',
)
replace_once(system, "            dashboard_url=dashboard_url,\n", "            dashboard_available=dashboard_available,\n")
replace_once(
    system,
    '''    def not_found(self, request: Request, *, dashboard_url: str | None = None) -> Response:\n''',
    '''    def not_found(self, request: Request, *, dashboard_available: bool) -> Response:\n''',
)
replace_once(system, "            dashboard_url=dashboard_url,\n", "            dashboard_available=dashboard_available,\n")
replace_once(
    system,
    '''    def internal_error(self, request: Request, *, dashboard_url: str | None = None) -> Response:\n''',
    '''    def internal_error(self, request: Request, *, dashboard_available: bool) -> Response:\n''',
)
replace_once(system, "            dashboard_url=dashboard_url,\n", "            dashboard_available=dashboard_available,\n")

auth_routes = Path("packages/rakit-web/src/rakit_web/auth_routes.py")
replace_once(auth_routes, '                "label": label,\n', '                "binding_label": label,\n')

authentication = Path("packages/rakit-web/src/rakit_web/security/authentication.py")
replace_once(authentication, 'LOGIN_PATH = "/auth/login"\nLOGOUT_PATH = "/auth/logout"\n', 'LOGIN_PATH = "/auth/login"\nLOGOUT_PATH = "/auth/logout"\n_AUTH_REASON_STATE_KEY = "rakit_auth_reason"\n\nBrowserForbiddenRenderer = Callable[[Request, bool], Response]\n')
replace_once(authentication, '            scope["state"]["rakit_auth_reason"] = AuthReason.SESSION_EXPIRED.value\n', '            scope["state"][_AUTH_REASON_STATE_KEY] = AuthReason.SESSION_EXPIRED.value\n')
replace_once(authentication, "def _is_generated_api_path(path: str) -> bool:\n", "def is_generated_api_path(path: str) -> bool:\n")
replace_once(authentication, "        browser_forbidden: Callable[[Request], Response] | None = None,\n", "        render_forbidden: BrowserForbiddenRenderer | None = None,\n")
replace_once(authentication, "        self._browser_forbidden = browser_forbidden\n", "        self._render_forbidden = render_forbidden\n")
replace_once(authentication, "        api_request = _is_generated_api_path(relative_path)\n", "        api_request = is_generated_api_path(relative_path)\n")
replace_once(authentication, '                scope.get("state", {}).get("rakit_auth_reason")\n', '                scope.get("state", {}).get(_AUTH_REASON_STATE_KEY)\n')
replace_once(
    authentication,
    '''            if self._browser_forbidden is not None:\n                await self._browser_forbidden(request)(scope, receive, send)\n            else:\n''',
    '''            if self._render_forbidden is not None:\n                dashboard_requirement = self._requirement_for("/", "GET")\n                dashboard_available = dashboard_requirement is None or dashboard_requirement.matches(\n                    principal, superuser_bypass=self._superuser_bypass\n                )\n                await self._render_forbidden(request, dashboard_available)(scope, receive, send)\n            else:\n''',
)

admin = Path("packages/rakit-web/src/rakit_web/admin.py")
replace_once(admin, "from ._paths import mounted_path\n", "")
replace_once(
    admin,
    '''    AuthorizationMiddleware,\n    PrincipalMiddleware,\n    build_requirement_resolver,\n''',
    '''    AuthorizationMiddleware,\n    PrincipalMiddleware,\n    admin_relative_path,\n    build_requirement_resolver,\n    is_generated_api_path,\n''',
)
old_handlers = '''        def _relative_request_path(request: Request) -> str:\n            relative_path = request.url.path\n            root_path = request.scope.get("root_path", "").rstrip("/")\n            if root_path and relative_path.startswith(root_path):\n                return relative_path[len(root_path) :] or "/"\n            return relative_path\n\n        async def http_error_handler(request: Request, exc: Exception) -> Response:\n            assert isinstance(exc, HTTPException)\n            relative_path = _relative_request_path(request)\n            if relative_path == "/api" or relative_path.startswith("/api/"):\n                request_id = request.scope.get("state", {}).get("request_id", "")\n                code = (\n                    "http.method_not_allowed"\n                    if exc.status_code == 405\n                    else "http.not_found"\n                    if exc.status_code == 404\n                    else "http.error"\n                )\n                headers = {"Cache-Control": "no-store", **(exc.headers or {})}\n                return JSONResponse(\n                    {\n                        "error": {"code": code, "message": str(exc.detail)},\n                        "request_id": request_id if isinstance(request_id, str) else "",\n                    },\n                    status_code=exc.status_code,\n                    headers=headers,\n                )\n            if exc.status_code == 404:\n                return system_pages.not_found(request, dashboard_url=_safe_dashboard_url(request))\n            return PlainTextResponse(\n                str(exc.detail),\n                status_code=exc.status_code,\n                headers=exc.headers,\n            )\n\n        async def unexpected_error_handler(request: Request, exc: Exception) -> Response:\n            del exc\n            relative_path = _relative_request_path(request)\n            if relative_path == "/api" or relative_path.startswith("/api/"):\n                return unexpected_api_error(request)\n            return system_pages.internal_error(request, dashboard_url=_safe_dashboard_url(request))\n\n        async def rakit_error_handler(_request: Request, exc: Exception) -> JSONResponse:\n            # Minimal error-to-HTTP translation: a RakitError already carries the\n            # HTTP status it intends (e.g. RESOURCE_NOT_FOUND -> 404), so honour it\n            # rather than letting it surface as an unhandled 500.\n            assert isinstance(exc, RakitError)\n            return JSONResponse(\n                exc.to_public_dict(),\n                status_code=exc.status_code,\n                headers={"Cache-Control": "no-store"},\n            )\n'''
new_handlers = '''        async def http_error_handler(request: Request, exc: Exception) -> Response:\n            assert isinstance(exc, HTTPException)\n            relative_path = admin_relative_path(request)\n            if is_generated_api_path(relative_path):\n                request_id = request.scope.get("state", {}).get("request_id", "")\n                code = (\n                    "http.method_not_allowed"\n                    if exc.status_code == 405\n                    else "http.not_found"\n                    if exc.status_code == 404\n                    else "http.error"\n                )\n                headers = {"Cache-Control": "no-store", **(exc.headers or {})}\n                return JSONResponse(\n                    {\n                        "error": {"code": code, "message": str(exc.detail)},\n                        "request_id": request_id if isinstance(request_id, str) else "",\n                    },\n                    status_code=exc.status_code,\n                    headers=headers,\n                )\n            if exc.status_code == 404:\n                return system_pages.not_found(\n                    request, dashboard_available=dashboard_available(request)\n                )\n            return PlainTextResponse(\n                str(exc.detail),\n                status_code=exc.status_code,\n                headers=exc.headers,\n            )\n\n        async def unexpected_error_handler(request: Request, exc: Exception) -> Response:\n            del exc\n            if is_generated_api_path(admin_relative_path(request)):\n                return unexpected_api_error(request)\n            return system_pages.internal_error(\n                request, dashboard_available=dashboard_available(request)\n            )\n\n        async def rakit_error_handler(request: Request, exc: Exception) -> Response:\n            assert isinstance(exc, RakitError)\n            if is_generated_api_path(admin_relative_path(request)):\n                return JSONResponse(\n                    exc.to_public_dict(),\n                    status_code=exc.status_code,\n                    headers={"Cache-Control": "no-store"},\n                )\n            if exc.status_code == 404:\n                return system_pages.not_found(\n                    request, dashboard_available=dashboard_available(request)\n                )\n            if exc.status_code == 403:\n                return system_pages.forbidden(\n                    request, dashboard_available=dashboard_available(request)\n                )\n            if exc.status_code >= 500 and not self.config.debug:\n                return system_pages.internal_error(\n                    request, dashboard_available=dashboard_available(request)\n                )\n            return JSONResponse(\n                exc.to_public_dict(),\n                status_code=exc.status_code,\n                headers={"Cache-Control": "no-store"},\n            )\n'''
replace_once(admin, old_handlers, new_handlers)
old_dashboard = '''        def _safe_dashboard_url(request: Request) -> str | None:\n            if self._auth_backend is None or self._session_store is None:\n                return mounted_path(request, "/")\n            principal = request.scope.get("state", {}).get("principal")\n            requirement = requirement_resolver("/", "GET")\n            if (\n                principal is not None\n                and principal.authenticated\n                and requirement is not None\n                and requirement.matches(principal, superuser_bypass=self._superuser_bypass)\n            ):\n                return mounted_path(request, "/")\n            return None\n'''
new_dashboard = '''        def dashboard_available(request: Request) -> bool:\n            requirement = requirement_resolver("/", "GET")\n            if requirement is None:\n                return True\n            principal = request.scope.get("state", {}).get("principal")\n            return bool(\n                principal is not None\n                and principal.authenticated\n                and requirement.matches(principal, superuser_bypass=self._superuser_bypass)\n            )\n'''
replace_once(admin, old_dashboard, new_dashboard)
replace_once(
    admin,
    '''                browser_forbidden=lambda request: system_pages.forbidden(\n                    request, dashboard_url=_safe_dashboard_url(request)\n                ),\n''',
    '''                render_forbidden=lambda request, can_return: system_pages.forbidden(\n                    request, dashboard_available=can_return\n                ),\n''',
)

base = Path("packages/rakit-web/src/rakit_web/templates/base.html")
text = base.read_text().replace("{{ label | default('Rakit') }}", "{{ binding_label | default(label | default('Rakit')) }}")
base.write_text(text)

login = Path("packages/rakit-web/src/rakit_web/templates/auth/login.html")
text = login.read_text().replace("{{ label }}", "{{ binding_label }}")
login.write_text(text)

page = Path("packages/rakit-web/src/rakit_web/templates/system/page.html")
text = page.read_text().replace("{{ label }}", "{{ binding_label }}")
page.write_text(text)

print("UI-06C contract alignment applied")
