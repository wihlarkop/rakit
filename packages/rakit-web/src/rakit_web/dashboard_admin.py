"""Dashboard-enabled public Admin facade."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from rakit_core.dashboard import DashboardDefinition, WidgetDefinition
from rakit_core.definitions import RouteDefinition
from rakit_core.di import ServiceResolver
from rakit_core.errors import ErrorCode, RakitError
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.types import ASGIApp, Receive, Scope, Send

from .admin import RequestContextMiddleware
from .dashboard_routes import DashboardBinding, build_dashboard_routes, widget_path
from .endpoint_admin import Admin as _EndpointAdmin
from .resource_routes import build_templates
from .security.authentication import (
    AuthorizationMiddleware,
    PrincipalMiddleware,
    admin_relative_path,
    build_requirement_resolver,
)
from .security.middleware import SecurityMiddleware


class _DashboardDispatchMiddleware:
    """Dispatch only the dashboard's exact HTTP paths to its isolated runtime."""

    def __init__(
        self,
        base_app: ASGIApp,
        dashboard_app: ASGIApp,
        paths: frozenset[str],
    ) -> None:
        self.base_app = base_app
        self.dashboard_app = dashboard_app
        self.paths = paths

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.base_app(scope, receive, send)
            return
        request = Request(scope, receive=receive)
        if admin_relative_path(request) in self.paths:
            await self.dashboard_app(scope, receive, send)
            return
        await self.base_app(scope, receive, send)


class Admin(_EndpointAdmin):
    """Public Admin facade with an automatic, permission-aware dashboard."""

    def _dashboard_widget_registry(self) -> dict[str, WidgetDefinition]:
        registry = self.__dict__.get("_dashboard_widgets")
        if registry is None:
            registry = {}
            self.__dict__["_dashboard_widgets"] = registry
        return registry

    def register_dashboard(self, definition: DashboardDefinition) -> None:
        if self.compiled is not None:
            raise RuntimeError("Cannot register a dashboard after compilation")
        if getattr(self, "_dashboard_definition", None) is not None:
            raise RakitError(
                code=ErrorCode.CONFIG_INVALID,
                message="Only one dashboard may be registered for an Admin.",
                status_code=500,
                details={"reason": "duplicate_dashboard"},
            )
        self._dashboard_definition = definition

    def register_widget(self, definition: WidgetDefinition) -> None:
        if self.compiled is not None:
            raise RuntimeError("Cannot register widgets after compilation")
        widgets = self._dashboard_widget_registry()
        widget_id = str(definition.widget_id)
        if widget_id in widgets:
            raise RakitError(
                code=ErrorCode.CONFIG_INVALID,
                message=f'Dashboard widget "{widget_id}" is already registered.',
                status_code=500,
                details={"widget_id": widget_id, "reason": "duplicate_widget"},
            )
        widgets[widget_id] = definition
        self.builder.add_route(
            RouteDefinition(
                route_name=f"rakit.dashboard.widget:{widget_id}",
                methods=("GET",),
                path=widget_path(widget_id),
                owner_id="rakit",
                framework_owned=True,
            )
        )

    def _resolved_dashboard(self) -> DashboardDefinition:
        widgets = self._dashboard_widget_registry()
        registered = getattr(self, "_dashboard_definition", None)
        if registered is not None:
            dashboard = registered
        else:
            dashboard = DashboardDefinition(
                dashboard_id="main",
                title=self.config.title,
                widgets=tuple(widgets),
            )
        missing = tuple(
            widget_id for widget_id in dashboard.widgets if str(widget_id) not in widgets
        )
        if missing:
            raise RakitError(
                code=ErrorCode.CONFIG_INVALID,
                message="Dashboard references unregistered widgets.",
                status_code=500,
                details={
                    "dashboard_id": str(dashboard.dashboard_id),
                    "widget_ids": tuple(str(item) for item in missing),
                    "reason": "unknown_dashboard_widget",
                },
            )
        return dashboard

    def asgi(self) -> ASGIApp:
        widgets = self._dashboard_widget_registry()
        dashboard = self._resolved_dashboard()
        base_app = super().asgi()
        compiled = self.compile()
        templates = build_templates(self._template_dirs)
        auth_enabled = self._auth_backend is not None and self._session_store is not None

        @asynccontextmanager
        async def operation_scope() -> AsyncIterator[ServiceResolver]:
            if self._application_resolver is None:
                raise RuntimeError("Application services are not available")
            async with (
                self._application_resolver.request_scope() as request_services,
                request_services.operation_scope() as operation_services,
            ):
                yield operation_services

        binding = DashboardBinding(
            dashboard=dashboard,
            resources=tuple(self._resource_definitions.values()),
            pages=compiled.compiled_pages,
            widgets=tuple(widgets.values()),
            templates=templates,
            admin_id=self.config.admin_id,
            auth_enabled=auth_enabled,
            superuser_bypass=self._superuser_bypass,
            operation_scope=operation_scope,
            default_widget_timeout_seconds=self._mutation_deadline_seconds,
        )
        dashboard_app: ASGIApp = Starlette(routes=build_dashboard_routes(binding))

        if auth_enabled:
            assert self._auth_backend is not None
            assert self._session_store is not None
            requirement_resolver = build_requirement_resolver(
                admin_id=self.config.admin_id,
                resource_paths={},
            )
            dashboard_app = AuthorizationMiddleware(
                dashboard_app,
                requirement_for=requirement_resolver,
                superuser_bypass=self._superuser_bypass,
            )
            dashboard_app = PrincipalMiddleware(
                dashboard_app,
                auth_backend=self._auth_backend,
                session_store=self._session_store,
            )

        dashboard_app = SecurityMiddleware(
            dashboard_app,
            allowed_hosts=self.config.security.allowed_hosts,
            content_security_policy_enabled=self.config.security.content_security_policy_enabled,
        )
        dashboard_app = RequestContextMiddleware(
            dashboard_app,
            admin_id=self.config.admin_id,
        )

        paths = frozenset({"/", *(widget_path(widget_id) for widget_id in widgets)})
        return _DashboardDispatchMiddleware(base_app, dashboard_app, paths)


__all__ = ["Admin"]
