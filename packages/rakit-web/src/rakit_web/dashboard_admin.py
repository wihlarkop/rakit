"""Dashboard-enabled public Admin facade."""

from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from dataclasses import replace
from http import HTTPStatus

from rakit_core.actions import ActionDefinition, ActionScope
from rakit_core.admin_types import ResourceAdmin
from rakit_core.dashboard import DashboardDefinition, WidgetDefinition
from rakit_core.definitions import PageDefinition, RouteDefinition
from rakit_core.di import ServiceResolver
from rakit_core.errors import ErrorCode, RakitError
from rakit_core.filters import ResourceFilter, effective_resource_filters
from rakit_core.identity import RecordIdentity
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.types import ASGIApp, Receive, Scope, Send

from .action_presentation import (
    bind_action_web_presentation,
    validate_action_presentations,
)
from .action_views import ActionView, ActionViewProvider, resolve_action_views
from .admin import RequestContextMiddleware
from .dashboard_routes import DashboardBinding, build_dashboard_routes, widget_path
from .endpoint_admin import Admin as _EndpointAdmin
from .field_presentation import (
    PresentationRegistry,
    default_presentation_registry,
    resolve_relationship_presentation,
)
from .form_routes import WriteResourceBinding
from .navigation import AdminNavigation, build_navigation_provider
from .page_presentation import PageWebPresentation
from .public_composition import resource_actions
from .resource_presentation import (
    ResourceWebPresentation,
    bind_resource_web_presentation,
    resource_web_presentation,
)
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


class _AdminNavigationMiddleware:
    """Expose a lazy navigation provider to every built-in template request."""

    def __init__(
        self,
        app: ASGIApp,
        provider: Callable[[Request], AdminNavigation],
    ) -> None:
        self.app = app
        self.provider = provider

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http":
            scope.setdefault("state", {})["rakit_navigation_provider"] = self.provider
        await self.app(scope, receive, send)


class _AdminActionViewMiddleware:
    """Expose the compiled action-view resolver without leaking it into core."""

    def __init__(self, app: ASGIApp, provider: ActionViewProvider) -> None:
        self.app = app
        self.provider = provider

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http":
            scope.setdefault("state", {})["rakit_action_view_provider"] = self.provider
        await self.app(scope, receive, send)


class Admin(_EndpointAdmin):
    """Public Admin facade with an automatic, permission-aware dashboard."""

    @property
    def presentations(self) -> PresentationRegistry:
        registry = getattr(self, "_rakit_presentation_registry", None)
        if registry is None:
            registry = default_presentation_registry()
            self._rakit_presentation_registry = registry
        return registry

    def register(
        self,
        admin_cls: type[ResourceAdmin],
        *,
        web: ResourceWebPresentation | None = None,
    ) -> None:
        """Register a resource plus optional Web-only presentation policy."""

        if web is not None and not isinstance(web, ResourceWebPresentation):
            raise RakitError(
                code=ErrorCode.CONFIG_INVALID_RESOURCE_POLICY,
                message="Invalid resource Web presentation declaration",
                status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
                details={
                    "resource_id": getattr(admin_cls, "resource_id", ""),
                    "reason": "invalid_web_presentation",
                },
            )
        presentation = web or ResourceWebPresentation()

        raw_filters = getattr(admin_cls, "filters", ())
        raw_filter_fields = getattr(admin_cls, "filter_fields", ())
        if (
            isinstance(raw_filters, list | tuple)
            and all(isinstance(definition, ResourceFilter) for definition in raw_filters)
            and isinstance(raw_filter_fields, list | tuple)
            and all(isinstance(field_name, str) for field_name in raw_filter_fields)
        ):
            known_filter_ids = {
                definition.filter_id
                for definition in effective_resource_filters(
                    tuple(raw_filters),
                    tuple(raw_filter_fields),
                )
            }
            unknown = sorted(set(presentation.filters.groups).difference(known_filter_ids))
            if unknown:
                raise RakitError(
                    code=ErrorCode.CONFIG_INVALID_RESOURCE_POLICY,
                    message="Invalid resource Web presentation declaration",
                    status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
                    details={
                        "resource_id": getattr(admin_cls, "resource_id", ""),
                        "reason": "unknown_web_filter_presentation",
                        "filter_ids": unknown,
                    },
                )

        declared_actions = resource_actions(
            admin_cls,
            existing_action_ids={str(action.action_id) for action in self.builder.actions},
        )
        try:
            validate_action_presentations(declared_actions, presentation.actions)
        except (TypeError, ValueError):
            raise RakitError(
                code=ErrorCode.CONFIG_INVALID_RESOURCE_POLICY,
                message="Invalid resource Web presentation declaration",
                status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
                details={
                    "resource_id": getattr(admin_cls, "resource_id", ""),
                    "reason": "invalid_web_action_presentation",
                },
            ) from None

        super().register(admin_cls)
        definition = self._resource_definitions[admin_cls.resource_id]
        bind_resource_web_presentation(definition, presentation)
        existing_write_binding = self._write_resource_bindings.get(admin_cls.resource_id)
        if existing_write_binding is not None:
            self._write_resource_bindings[admin_cls.resource_id] = self._configured_write_binding(
                admin_cls.resource_id, existing_write_binding, presentation
            )
        for action in declared_actions:
            action_id = str(action.action_id)
            configured = presentation.actions.get(action_id)
            if configured is not None:
                bind_action_web_presentation(action, configured)

    def _configured_write_binding(
        self,
        resource_id: str,
        binding: WriteResourceBinding,
        web: ResourceWebPresentation,
    ) -> WriteResourceBinding:
        known_fields = {field.field_id for field in binding.form_schema.fields}
        unknown_fields = sorted(set(web.fields).difference(known_fields))
        relationship_form = binding.relationship_form
        known_relationships = (
            {editor.relationship_id for editor in relationship_form.editors}
            if relationship_form is not None
            else set()
        )
        unknown_relationships = sorted(set(web.relationships).difference(known_relationships))
        if unknown_fields or unknown_relationships:
            raise RakitError(
                code=ErrorCode.CONFIG_INVALID_RESOURCE_POLICY,
                message="Invalid resource Web presentation declaration",
                status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
                details={
                    "resource_id": resource_id,
                    "reason": "unknown_web_widget_presentation",
                    "field_ids": unknown_fields,
                    "relationship_ids": unknown_relationships,
                },
            )
        if relationship_form is not None:
            try:
                relationship_form = replace(
                    relationship_form,
                    editors=tuple(
                        replace(
                            editor,
                            presentation=resolve_relationship_presentation(
                                editor.relationship.definition.presentation,
                                web.relationships.get(editor.relationship_id),
                            ),
                        )
                        for editor in relationship_form.editors
                    ),
                )
            except (TypeError, ValueError):
                raise RakitError(
                    code=ErrorCode.CONFIG_INVALID_RESOURCE_POLICY,
                    message="Invalid resource Web presentation declaration",
                    status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
                    details={
                        "resource_id": resource_id,
                        "reason": "invalid_relationship_widget_presentation",
                    },
                ) from None
        return replace(
            binding,
            field_presentations=web.fields,
            presentation_registry=self.presentations,
            relationship_form=relationship_form,
        )

    def register_write_resource(self, resource_id: str, binding: WriteResourceBinding) -> None:
        definition = self._resource_definitions.get(resource_id)
        if definition is None:
            super().register_write_resource(resource_id, binding)
            return
        configured = self._configured_write_binding(
            resource_id, binding, resource_web_presentation(definition)
        )
        super().register_write_resource(resource_id, configured)

    def register_page(
        self,
        definition: PageDefinition,
        *,
        actions: tuple[ActionDefinition, ...] = (),
        web: PageWebPresentation | None = None,
    ) -> None:
        """Register a public page plus optional Web-only action presentation."""

        if web is not None and not isinstance(web, PageWebPresentation):
            raise RakitError(
                code=ErrorCode.CONFIG_INVALID,
                message="Invalid page Web presentation declaration",
                status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
                details={
                    "page_id": str(definition.page_id),
                    "reason": "invalid_web_action_presentation",
                },
            )
        presentation = web or PageWebPresentation()
        try:
            validate_action_presentations(actions, presentation.actions)
        except (TypeError, ValueError):
            raise RakitError(
                code=ErrorCode.CONFIG_INVALID,
                message="Invalid page Web presentation declaration",
                status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
                details={
                    "page_id": str(definition.page_id),
                    "reason": "invalid_web_action_presentation",
                },
            ) from None

        super().register_page(definition, actions=actions)
        for action in actions:
            action_id = str(action.action_id)
            configured = presentation.actions.get(action_id)
            if configured is not None:
                bind_action_web_presentation(action, configured)

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
                status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
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
                status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
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
                status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
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
        compiled = self.compile()
        auth_enabled = self._auth_backend is not None and self._session_store is not None
        navigation_provider = build_navigation_provider(
            title=self.config.title,
            admin_id=self.config.admin_id,
            resources=tuple(self._resource_definitions.values()),
            pages=compiled.compiled_pages,
            auth_enabled=auth_enabled,
            superuser_bypass=self._superuser_bypass,
        )

        async def action_view_provider(
            request: Request,
            owner_id: str,
            scope: ActionScope,
            identity: RecordIdentity | None,
            record: object | None,
        ) -> tuple[ActionView, ...]:
            return await resolve_action_views(
                request=request,
                routes=compiled.action_routes,
                admin_id=self.config.admin_id,
                owner_id=owner_id,
                scope=scope,
                superuser_bypass=self._superuser_bypass,
                identity=identity,
                record=record,
            )

        base_app = super().asgi()
        templates = build_templates(self._template_dirs)

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
        app = _DashboardDispatchMiddleware(base_app, dashboard_app, paths)
        app = _AdminActionViewMiddleware(app, action_view_provider)
        return _AdminNavigationMiddleware(app, navigation_provider)


__all__ = ["Admin"]
