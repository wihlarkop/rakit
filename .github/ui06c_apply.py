from pathlib import Path


def replace_once(path: Path, old: str, new: str) -> None:
    text = path.read_text()
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"expected one match in {path}: {old[:90]!r}; got {count}")
    path.write_text(text.replace(old, new, 1))


auth_routes = Path("packages/rakit-web/src/rakit_web/auth_routes.py")
replace_once(
    auth_routes,
    "from ._paths import mounted_path as _mounted_path\n",
    "from ._paths import mounted_path as _mounted_path\nfrom .auth_state import AuthReason\nfrom .system_responses import auth_reason_message\n",
)
replace_once(
    auth_routes,
    '''    templates: Jinja2Templates,\n    admin_id: str,\n''',
    '''    templates: Jinja2Templates,\n    label: str,\n    admin_id: str,\n''',
)
replace_once(
    auth_routes,
    '''    def _render_login(request: Request, *, error: str | None, status_code: int = 200) -> Response:\n''',
    '''    def _render_login(\n        request: Request,\n        *,\n        error: str | None,\n        reason_message: tuple[str, str] | None = None,\n        status_code: int = 200,\n    ) -> Response:\n''',
)
replace_once(
    auth_routes,
    '''                "error": error,\n                "login_url": _mounted_path(request, "/auth/login"),\n''',
    '''                "error": error,\n                "reason_message": reason_message,\n                "label": label,\n                "login_url": _mounted_path(request, "/auth/login"),\n''',
)
replace_once(
    auth_routes,
    '''                "rakit_shell_enabled": False,\n''',
    '''                "rakit_shell_enabled": False,\n                "rakit_shell_mode": "auth",\n''',
)
replace_once(
    auth_routes,
    '''    async def login_get(request: Request) -> Response:\n        return _render_login(request, error=None)\n''',
    '''    async def login_get(request: Request) -> Response:\n        return _render_login(\n            request,\n            error=None,\n            reason_message=auth_reason_message(request.query_params.get("reason")),\n        )\n''',
)
replace_once(
    auth_routes,
    '''        response = RedirectResponse(url=_mounted_path(request, "/auth/login"), status_code=303)\n''',
    '''        response = RedirectResponse(\n            url=f"{_mounted_path(request, '/auth/login')}?reason={AuthReason.SIGNED_OUT.value}",\n            status_code=303,\n        )\n''',
)

authentication = Path("packages/rakit-web/src/rakit_web/security/authentication.py")
replace_once(
    authentication,
    "from starlette.responses import JSONResponse, PlainTextResponse, RedirectResponse\n",
    "from starlette.responses import JSONResponse, PlainTextResponse, RedirectResponse, Response\n",
)
replace_once(
    authentication,
    "from .._paths import mounted_path\n",
    "from .._paths import mounted_path\nfrom ..auth_state import AuthReason\n",
)
replace_once(
    authentication,
    '''        scope["state"]["principal"] = principal\n        if session_id is not None:\n''',
    '''        scope["state"]["principal"] = principal\n        if clear_session_cookie:\n            scope["state"]["rakit_auth_reason"] = AuthReason.SESSION_EXPIRED.value\n        if session_id is not None:\n''',
)
replace_once(
    authentication,
    '''        requirement_for: Callable[..., PermissionRequirement | None],\n        superuser_bypass: bool = True,\n    ) -> None:\n        self.app = app\n        self._requirement_for = requirement_for\n        self._superuser_bypass = superuser_bypass\n''',
    '''        requirement_for: Callable[..., PermissionRequirement | None],\n        superuser_bypass: bool = True,\n        browser_forbidden: Callable[[Request], Response] | None = None,\n    ) -> None:\n        self.app = app\n        self._requirement_for = requirement_for\n        self._superuser_bypass = superuser_bypass\n        self._browser_forbidden = browser_forbidden\n''',
)
replace_once(
    authentication,
    '''            # Browser requests retain the existing login redirect behavior.\n            await RedirectResponse(\n                url=mounted_path(request, LOGIN_PATH),\n                status_code=303,\n                headers={"Cache-Control": "no-store"},\n            )(scope, receive, send)\n''',
    '''            # Browser requests retain the login redirect behavior and expose\n            # only a closed reason code when a previously-present session expired.\n            login_url = mounted_path(request, LOGIN_PATH)\n            if (\n                scope.get("state", {}).get("rakit_auth_reason")\n                == AuthReason.SESSION_EXPIRED.value\n            ):\n                login_url = f"{login_url}?reason={AuthReason.SESSION_EXPIRED.value}"\n            await RedirectResponse(\n                url=login_url,\n                status_code=303,\n                headers={"Cache-Control": "no-store"},\n            )(scope, receive, send)\n''',
)
replace_once(
    authentication,
    '''            await PlainTextResponse(\n                "Forbidden", status_code=403, headers={"Cache-Control": "no-store"}\n            )(scope, receive, send)\n            return\n''',
    '''            if self._browser_forbidden is not None:\n                await self._browser_forbidden(request)(scope, receive, send)\n            else:\n                await PlainTextResponse(\n                    "Forbidden", status_code=403, headers={"Cache-Control": "no-store"}\n                )(scope, receive, send)\n            return\n''',
)

admin = Path("packages/rakit-web/src/rakit_web/admin.py")
replace_once(
    admin,
    "from .action_routes import (\n",
    "from ._paths import mounted_path\nfrom .action_routes import (\n",
)
replace_once(
    admin,
    '''from .security.validation import (\n''',
    '''from .system_responses import SystemPageRenderer, unexpected_api_error\nfrom .security.validation import (\n''',
)
old_handlers = '''        async def http_error_handler(request: Request, exc: Exception) -> Response:\n            assert isinstance(exc, HTTPException)\n            relative_path = request.url.path\n            root_path = request.scope.get("root_path", "").rstrip("/")\n            if root_path and relative_path.startswith(root_path):\n                relative_path = relative_path[len(root_path) :] or "/"\n            if relative_path == "/api" or relative_path.startswith("/api/"):\n                request_id = request.scope.get("state", {}).get("request_id", "")\n                code = (\n                    "http.method_not_allowed"\n                    if exc.status_code == 405\n                    else "http.not_found"\n                    if exc.status_code == 404\n                    else "http.error"\n                )\n                headers = {"Cache-Control": "no-store", **(exc.headers or {})}\n                return JSONResponse(\n                    {\n                        "error": {"code": code, "message": str(exc.detail)},\n                        "request_id": request_id if isinstance(request_id, str) else "",\n                    },\n                    status_code=exc.status_code,\n                    headers=headers,\n                )\n            return PlainTextResponse(\n                str(exc.detail),\n                status_code=exc.status_code,\n                headers=exc.headers,\n            )\n'''
new_handlers = '''        def _relative_request_path(request: Request) -> str:\n            relative_path = request.url.path\n            root_path = request.scope.get("root_path", "").rstrip("/")\n            if root_path and relative_path.startswith(root_path):\n                return relative_path[len(root_path) :] or "/"\n            return relative_path\n\n        async def http_error_handler(request: Request, exc: Exception) -> Response:\n            assert isinstance(exc, HTTPException)\n            relative_path = _relative_request_path(request)\n            if relative_path == "/api" or relative_path.startswith("/api/"):\n                request_id = request.scope.get("state", {}).get("request_id", "")\n                code = (\n                    "http.method_not_allowed"\n                    if exc.status_code == 405\n                    else "http.not_found"\n                    if exc.status_code == 404\n                    else "http.error"\n                )\n                headers = {"Cache-Control": "no-store", **(exc.headers or {})}\n                return JSONResponse(\n                    {\n                        "error": {"code": code, "message": str(exc.detail)},\n                        "request_id": request_id if isinstance(request_id, str) else "",\n                    },\n                    status_code=exc.status_code,\n                    headers=headers,\n                )\n            if exc.status_code == 404:\n                return system_pages.not_found(\n                    request, dashboard_url=_safe_dashboard_url(request)\n                )\n            return PlainTextResponse(\n                str(exc.detail),\n                status_code=exc.status_code,\n                headers=exc.headers,\n            )\n\n        async def unexpected_error_handler(request: Request, exc: Exception) -> Response:\n            del exc\n            relative_path = _relative_request_path(request)\n            if relative_path == "/api" or relative_path.startswith("/api/"):\n                return unexpected_api_error(request)\n            return system_pages.internal_error(\n                request, dashboard_url=_safe_dashboard_url(request)\n            )\n'''
replace_once(admin, old_handlers, new_handlers)
replace_once(
    admin,
    '''        templates = build_templates(self._template_dirs)\n        bindings: dict[str, ResourceBinding] = {}\n''',
    '''        templates = build_templates(self._template_dirs)\n        system_pages = SystemPageRenderer(templates=templates, label=self.config.title)\n        bindings: dict[str, ResourceBinding] = {}\n''',
)
replace_once(
    admin,
    '''        requirement_resolver = build_requirement_resolver(\n            admin_id=self.config.admin_id,\n''',
    '''        requirement_resolver = build_requirement_resolver(\n            admin_id=self.config.admin_id,\n''',
)
# Insert the permission-aware dashboard URL helper immediately after resolver construction.
needle = '''            generated_api_requirements=generated_rest_requirement_map(\n                self.compiled.compiled_resource_apis,\n                admin_id=self.config.admin_id,\n            ),\n        )\n        if self._session_store is not None and self.config.security.secret_key is not None:\n'''
replacement = '''            generated_api_requirements=generated_rest_requirement_map(\n                self.compiled.compiled_resource_apis,\n                admin_id=self.config.admin_id,\n            ),\n        )\n\n        def _safe_dashboard_url(request: Request) -> str | None:\n            if self._auth_backend is None or self._session_store is None:\n                return mounted_path(request, "/")\n            principal = request.scope.get("state", {}).get("principal")\n            requirement = requirement_resolver("/", "GET")\n            if (\n                principal is not None\n                and principal.authenticated\n                and requirement is not None\n                and requirement.matches(principal, superuser_bypass=self._superuser_bypass)\n            ):\n                return mounted_path(request, "/")\n            return None\n\n        if self._session_store is not None and self.config.security.secret_key is not None:\n'''
replace_once(admin, needle, replacement)
replace_once(
    admin,
    '''        app = Starlette(\n            debug=self.config.debug,\n            routes=[Route("/", home)],\n            lifespan=lifespan,\n            exception_handlers={\n                RakitError: rakit_error_handler,\n                HTTPException: http_error_handler,\n            },\n        )\n''',
    '''        app = Starlette(\n            debug=self.config.debug,\n            routes=[Route("/", home)],\n            lifespan=lifespan,\n            exception_handlers={\n                RakitError: rakit_error_handler,\n                HTTPException: http_error_handler,\n            },\n        )\n        if not self.config.debug:\n            app.add_exception_handler(Exception, unexpected_error_handler)\n''',
)
replace_once(
    admin,
    '''                rate_limiter=self._login_rate_limiter,\n                templates=templates,\n                admin_id=self.config.admin_id,\n''',
    '''                rate_limiter=self._login_rate_limiter,\n                templates=templates,\n                label=self.config.title,\n                admin_id=self.config.admin_id,\n''',
)
replace_once(
    admin,
    '''            inner_app = AuthorizationMiddleware(\n                inner_app,\n                requirement_for=requirement_resolver,\n                superuser_bypass=self._superuser_bypass,\n            )\n''',
    '''            inner_app = AuthorizationMiddleware(\n                inner_app,\n                requirement_for=requirement_resolver,\n                superuser_bypass=self._superuser_bypass,\n                browser_forbidden=lambda request: system_pages.forbidden(\n                    request, dashboard_url=_safe_dashboard_url(request)\n                ),\n            )\n''',
)

print("UI-06C auth/system source patch applied")
