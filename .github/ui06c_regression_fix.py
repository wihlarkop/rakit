from pathlib import Path


def replace_once(path: Path, old: str, new: str) -> None:
    text = path.read_text()
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"expected one match in {path}: {old[:100]!r}; got {count}")
    path.write_text(text.replace(old, new, 1))


# Preserve the established accessibility markup contract while keeping the new shell modes.
base = Path("packages/rakit-web/src/rakit_web/templates/base.html")
replace_once(
    base,
    '''    <a href="#rakit-main-content" class="sr-only z-50 rounded-rakit-sm bg-rakit-surface px-3 py-2 text-sm font-medium text-rakit-text shadow-rakit-md focus:not-sr-only focus:fixed focus:left-4 focus:top-4">Skip to main content</a>\n''',
    '''    <a\n      href="#rakit-main-content"\n      class="sr-only z-50 rounded-rakit-sm bg-rakit-surface px-3 py-2 text-sm font-medium text-rakit-text shadow-rakit-md focus:not-sr-only focus:fixed focus:left-4 focus:top-4"\n    >Skip to main content</a>\n''',
)

# Keep the legacy logout Location exact. The closed signed_out reason remains accepted by
# login presentation, but the logout transport itself stays byte-for-byte compatible.
auth_routes = Path("packages/rakit-web/src/rakit_web/auth_routes.py")
replace_once(auth_routes, "from .auth_state import AuthReason\n", "")
replace_once(
    auth_routes,
    '''        response = RedirectResponse(\n            url=f"{_mounted_path(request, '/auth/login')}?reason={AuthReason.SIGNED_OUT.value}",\n            status_code=303,\n        )\n''',
    '''        response = RedirectResponse(\n            url=_mounted_path(request, "/auth/login"),\n            status_code=303,\n        )\n''',
)

# Distinguish a genuinely stale/missing session row from a principal that was revoked or
# deactivated. Both clear the cookie, but only the former earns session_expired feedback.
authentication = Path("packages/rakit-web/src/rakit_web/security/authentication.py")
replace_once(
    authentication,
    '''    async def _resolve(self, request: Request) -> tuple[Principal, bool, str | None]:\n''',
    '''    async def _resolve(\n        self, request: Request\n    ) -> tuple[Principal, bool, str | None, AuthReason | None]:\n''',
)
replace_once(
    authentication,
    '''        raw_token = request.cookies.get(SESSION_COOKIE_NAME)\n        if not raw_token:\n            return ANONYMOUS_PRINCIPAL, False, None\n        record = await self._session_store.resolve(raw_token)\n        if record is None:\n            return ANONYMOUS_PRINCIPAL, True, None\n''',
    '''        raw_token = request.cookies.get(SESSION_COOKIE_NAME)\n        if not raw_token:\n            return ANONYMOUS_PRINCIPAL, False, None, None\n        record = await self._session_store.resolve(raw_token)\n        if record is None:\n            return ANONYMOUS_PRINCIPAL, True, None, AuthReason.SESSION_EXPIRED\n''',
)
replace_once(
    authentication,
    '''            await self._session_store.revoke(record.session_id)\n            return ANONYMOUS_PRINCIPAL, True, None\n        return principal, False, record.session_id\n''',
    '''            await self._session_store.revoke(record.session_id)\n            return ANONYMOUS_PRINCIPAL, True, None, None\n        return principal, False, record.session_id, None\n''',
)
replace_once(
    authentication,
    '''        principal, clear_session_cookie, session_id = await self._resolve(request)\n        scope.setdefault("state", {})\n        scope["state"]["principal"] = principal\n        if clear_session_cookie:\n            scope["state"][_AUTH_REASON_STATE_KEY] = AuthReason.SESSION_EXPIRED.value\n''',
    '''        principal, clear_session_cookie, session_id, auth_reason = await self._resolve(request)\n        scope.setdefault("state", {})\n        scope["state"]["principal"] = principal\n        if auth_reason is not None:\n            scope["state"][_AUTH_REASON_STATE_KEY] = auth_reason.value\n''',
)

print("UI-06C compatibility regressions fixed")
