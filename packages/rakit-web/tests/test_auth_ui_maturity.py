from typing import Any, cast

import httpx
import pytest
from rakit_core.auth import ANONYMOUS_PRINCIPAL, AuthBackend, Principal, SessionStore
from rakit_core.permissions import PermissionRequirement
from rakit_web.resource_routes import build_templates
from rakit_web.security.authentication import (
    AuthorizationMiddleware,
    PrincipalMiddleware,
    is_generated_api_path,
)
from rakit_web.system_responses import SystemPageRenderer, auth_reason_message, unexpected_api_error
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import PlainTextResponse, Response
from starlette.routing import Mount, Route
from starlette.types import ASGIApp, Receive, Scope, Send


class _MissingSessionStore:
    async def resolve(self, raw_token: str) -> None:
        del raw_token
        return None


class _UnusedAuthBackend:
    async def resolve_principal(self, subject_id: str) -> Principal | None:
        del subject_id
        raise AssertionError("missing sessions must not resolve a principal")


class _PrincipalState:
    def __init__(self, app: ASGIApp, principal: Principal) -> None:
        self.app = app
        self.principal = principal

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        scope.setdefault("state", {})["principal"] = self.principal
        await self.app(scope, receive, send)


def _requirement(path: str, method: str) -> PermissionRequirement | None:
    del method
    if path.startswith("/auth/"):
        return None
    return PermissionRequirement.all_of("operations.access")


def _system_renderer() -> SystemPageRenderer:
    return SystemPageRenderer(templates=build_templates(()), label="Operations")


def _protected_app(*, principal: Principal | None = None) -> ASGIApp:
    async def secret(_request: Request) -> Response:
        return PlainTextResponse("secret")

    inner = Starlette(
        routes=[
            Route("/secret", secret),
            Route("/api/secret", secret),
            Route("/auth/login", secret),
        ]
    )
    renderer = _system_renderer()
    app: ASGIApp = AuthorizationMiddleware(
        inner,
        requirement_for=_requirement,
        render_forbidden=lambda request, can_return: renderer.forbidden(
            request, dashboard_available=can_return
        ),
    )
    if principal is not None:
        app = _PrincipalState(app, principal)
    return app


def test_auth_reason_whitelist_never_reflects_raw_input() -> None:
    assert auth_reason_message(None) is None
    assert auth_reason_message("<script>alert('secret')</script>") is None
    assert auth_reason_message("session_expired") == (
        "warning",
        "Your session has expired. Sign in again to continue.",
    )
    assert auth_reason_message("signed_out") == (
        "success",
        "You have signed out successfully.",
    )


def test_generated_api_classifier_is_path_exact() -> None:
    assert is_generated_api_path("/api")
    assert is_generated_api_path("/api/items")
    assert not is_generated_api_path("/apiary")
    assert not is_generated_api_path("/items/api")


@pytest.mark.anyio
async def test_clean_anonymous_and_stale_session_redirects_are_distinct() -> None:
    authorization = _protected_app()
    stale_app = PrincipalMiddleware(
        authorization,
        auth_backend=cast(AuthBackend, _UnusedAuthBackend()),
        session_store=cast(SessionStore, _MissingSessionStore()),
    )

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=authorization),
        base_url="http://test",
        follow_redirects=False,
    ) as clean_client:
        clean = await clean_client.get("/secret")

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=stale_app),
        base_url="http://test",
        follow_redirects=False,
        cookies={"rakit_session": "stale-token"},
    ) as stale_client:
        stale = await stale_client.get("/secret")
        stale_api = await stale_client.get("/api/secret")

    assert clean.status_code == 303
    assert clean.headers["location"] == "/auth/login"
    assert stale.status_code == 303
    assert stale.headers["location"] == "/auth/login?reason=session_expired"
    assert "rakit_session=" in stale.headers.get("set-cookie", "")
    assert stale_api.status_code == 401
    assert stale_api.headers["content-type"].startswith("application/json")
    assert stale_api.json()["error"] == {
        "code": "auth.unauthenticated",
        "message": "Authentication is required.",
    }
    assert "session_expired" not in stale_api.text


@pytest.mark.anyio
async def test_browser_and_api_forbidden_keep_separate_response_contracts() -> None:
    principal = Principal(subject_id="user-1", authenticated=True, permissions=frozenset())
    app = _protected_app(principal=principal)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        browser = await client.get("/secret")
        api = await client.get("/api/secret")

    assert browser.status_code == 403
    assert browser.headers["content-type"].startswith("text/html")
    assert "Access denied" in browser.text
    assert "operations.access" not in browser.text
    assert "Back to dashboard" not in browser.text
    assert "data-rakit-theme-control" in browser.text
    assert "data-rakit-desktop-navigation" not in browser.text

    assert api.status_code == 403
    assert api.headers["content-type"].startswith("application/json")
    assert api.json()["error"] == {
        "code": "auth.forbidden",
        "message": "Permission denied.",
    }
    assert "Access denied" not in api.text


@pytest.mark.anyio
async def test_system_pages_use_mounted_dashboard_only_when_allowed() -> None:
    renderer = _system_renderer()

    async def missing(request: Request) -> Response:
        return renderer.not_found(request, dashboard_available=True)

    async def forbidden(request: Request) -> Response:
        return renderer.forbidden(request, dashboard_available=False)

    inner = Starlette(routes=[Route("/missing", missing), Route("/forbidden", forbidden)])
    app = Starlette(routes=[Mount("/admin", app=inner)])

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        missing_response = await client.get("/admin/missing")
        forbidden_response = await client.get("/admin/forbidden")

    assert missing_response.status_code == 404
    assert 'href="/admin/"' in missing_response.text
    assert "Back to dashboard" in missing_response.text
    assert "data-rakit-theme-control" in missing_response.text
    assert forbidden_response.status_code == 403
    assert "Back to dashboard" not in forbidden_response.text


@pytest.mark.anyio
async def test_production_system_500_and_api_helper_do_not_accept_exception_text() -> None:
    seeded_secret = "postgresql://user:secret@db/private + /srv/app/internal.py"
    renderer = _system_renderer()

    async def browser_failure(request: Request) -> Response:
        request.scope.setdefault("state", {})["request_id"] = "req-browser"
        return renderer.internal_error(request, dashboard_available=False)

    async def api_failure(request: Request) -> Response:
        request.scope.setdefault("state", {})["request_id"] = "req-api"
        return unexpected_api_error(request)

    app = Starlette(routes=[Route("/failure", browser_failure), Route("/api/failure", api_failure)])
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        browser = await client.get("/failure")
        api = await client.get("/api/failure")

    assert browser.status_code == 500
    assert "Something went wrong" in browser.text
    assert "req-browser" in browser.text
    assert seeded_secret not in browser.text
    assert api.status_code == 500
    assert api.json() == {
        "error": {"code": "internal.error", "message": "Internal server error."},
        "request_id": "req-api",
    }
    assert seeded_secret not in api.text


def test_anonymous_constant_remains_unauthenticated() -> None:
    # A tiny guard against accidentally treating a missing state principal as a partial session.
    assert ANONYMOUS_PRINCIPAL.authenticated is False
    assert cast(Any, ANONYMOUS_PRINCIPAL).permissions == frozenset()
