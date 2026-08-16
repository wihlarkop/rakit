"""Permission-aware dashboard rendering and isolated widget execution."""

from __future__ import annotations

import inspect
from collections.abc import Callable, Iterable
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass

import anyio
import structlog
from rakit_core.auth import Principal
from rakit_core.dashboard import (
    DashboardDefinition,
    LauncherItem,
    ListWidgetResult,
    StatWidgetResult,
    TableWidgetResult,
    TemplateWidgetResult,
    TextWidgetResult,
    WidgetContext,
    WidgetDefinition,
    WidgetErrorResult,
    WidgetLoadingMode,
    WidgetResult,
)
from rakit_core.definitions import CompiledPageDefinition, ResourceDefinition
from rakit_core.di import ServiceResolver
from rakit_core.operations import (
    CancellationContext,
    Deadline,
    OperationContext,
    activate_operation_context,
    new_operation_id,
)
from rakit_core.permissions import PermissionRequirement
from starlette.requests import Request
from starlette.responses import PlainTextResponse, Response
from starlette.routing import Route
from starlette.templating import Jinja2Templates

from ._paths import mounted_path

logger = structlog.get_logger(__name__)

_DASHBOARD_WIDGET_PREFIX = "/_dashboard/widgets"
_DEFAULT_WIDGET_TIMEOUT_SECONDS = 10.0
_WIDGET_RESULT_TYPES = (
    StatWidgetResult,
    TextWidgetResult,
    ListWidgetResult,
    TableWidgetResult,
    TemplateWidgetResult,
    WidgetErrorResult,
)


@dataclass(frozen=True)
class DashboardBinding:
    dashboard: DashboardDefinition
    resources: tuple[ResourceDefinition, ...]
    pages: tuple[CompiledPageDefinition, ...]
    widgets: tuple[WidgetDefinition, ...]
    templates: Jinja2Templates
    admin_id: str
    auth_enabled: bool
    superuser_bypass: bool
    operation_scope: Callable[[], AbstractAsyncContextManager[ServiceResolver]] | None = None
    default_widget_timeout_seconds: float = _DEFAULT_WIDGET_TIMEOUT_SECONDS

    def __post_init__(self) -> None:
        widget_ids = {str(widget.widget_id) for widget in self.widgets}
        missing = tuple(
            widget_id for widget_id in self.dashboard.widgets if widget_id not in widget_ids
        )
        if missing:
            missing_ids = ", ".join(str(item) for item in missing)
            raise ValueError(f"Dashboard references unregistered widgets: {missing_ids}")
        if self.default_widget_timeout_seconds <= 0:
            raise ValueError("Dashboard widget timeout must be positive")

    @property
    def widgets_by_id(self) -> dict[str, WidgetDefinition]:
        return {str(widget.widget_id): widget for widget in self.widgets}


def widget_path(widget_id: str) -> str:
    return f"{_DASHBOARD_WIDGET_PREFIX}/{widget_id}"


def _principal(request: Request) -> Principal | None:
    value = request.scope.get("state", {}).get("principal")
    return value if isinstance(value, Principal) else None


def _allowed(
    binding: DashboardBinding,
    principal: Principal | None,
    requirement: PermissionRequirement | None,
) -> bool:
    if requirement is None:
        return True
    if not binding.auth_enabled:
        return True
    return bool(
        principal is not None
        and requirement.matches(
            principal,
            superuser_bypass=binding.superuser_bypass,
        )
    )


def _resource_requirement(
    binding: DashboardBinding,
    resource_id: str,
) -> PermissionRequirement:
    return PermissionRequirement.all_of(f"{binding.admin_id}.resources.{resource_id}.read")


def _automatic_launchers(binding: DashboardBinding) -> tuple[LauncherItem, ...]:
    resource_items = tuple(
        LauncherItem(
            launcher_id=f"resource_{resource.resource_id}",
            label=resource.label,
            path=resource.path,
            permission=_resource_requirement(binding, str(resource.resource_id)),
        )
        for resource in binding.resources
    )
    page_items = tuple(
        LauncherItem(
            launcher_id=f"page_{page.definition.page_id}",
            label=page.definition.label,
            path=page.definition.path,
            permission=page.permission,
        )
        for page in binding.pages
    )
    return (*resource_items, *page_items)


def visible_launchers(
    binding: DashboardBinding,
    request: Request,
) -> tuple[LauncherItem, ...]:
    principal = _principal(request)
    candidates = binding.dashboard.launchers or _automatic_launchers(binding)
    return tuple(
        launcher for launcher in candidates if _allowed(binding, principal, launcher.permission)
    )


def visible_widgets(
    binding: DashboardBinding,
    request: Request,
) -> tuple[WidgetDefinition, ...]:
    principal = _principal(request)
    by_id = binding.widgets_by_id
    selected = (
        tuple(by_id[str(widget_id)] for widget_id in binding.dashboard.widgets)
        if binding.dashboard.widgets
        else binding.widgets
    )
    visible = tuple(
        widget for widget in selected if _allowed(binding, principal, widget.permission)
    )
    registration_order = {
        str(widget.widget_id): index for index, widget in enumerate(binding.widgets)
    }
    return tuple(
        sorted(
            visible,
            key=lambda widget: (
                widget.layout.priority,
                registration_order[str(widget.widget_id)],
            ),
        )
    )


def _request_state(request: Request) -> dict[str, object]:
    state = request.scope.get("state", {})
    return state if isinstance(state, dict) else {}


async def _execute_widget(
    binding: DashboardBinding,
    request: Request,
    widget: WidgetDefinition,
) -> WidgetResult:
    timeout_seconds = widget.timeout_seconds or binding.default_widget_timeout_seconds
    deadline = Deadline.after(timeout_seconds)
    state = _request_state(request)
    principal = _principal(request)
    services: ServiceResolver | None = None

    async def execute() -> WidgetResult:
        operation_context = OperationContext(
            deadline=deadline,
            cancellation=CancellationContext(),
            request_id=str(state.get("request_id", "")),
            operation_id=new_operation_id(),
            principal=principal,
            principal_id=(principal.subject_id or "") if principal is not None else "",
            session_id=str(state.get("session_id", "")),
            admin_id=binding.admin_id,
            resource_id=f"dashboard:{binding.dashboard.dashboard_id}",
            operation=f"dashboard.widget:{widget.widget_id}",
            permissions=(widget.permission.permissions if widget.permission is not None else ()),
            permission_requirement=widget.permission,
            services=services,
        )
        context = WidgetContext(
            widget_id=widget.widget_id,
            principal=principal,
            services=services,
        )
        with activate_operation_context(operation_context):
            operation_context.checkpoint()
            value = widget.loader(context)
            result = await value if inspect.isawaitable(value) else value
            if not isinstance(result, _WIDGET_RESULT_TYPES):
                raise TypeError("Dashboard widget loaders must return a WidgetResult")
            return result.model_copy(
                update={
                    "label": widget.label,
                    "layout": widget.layout,
                    "loading": widget.loading,
                }
            )

    try:
        with anyio.fail_after(timeout_seconds):
            if binding.operation_scope is not None:
                async with binding.operation_scope() as operation_services:
                    services = operation_services
                    return await execute()
            return await execute()
    except Exception as exc:
        logger.warning(
            "dashboard.widget.failed",
            dashboard_id=str(binding.dashboard.dashboard_id),
            widget_id=str(widget.widget_id),
            error_type=type(exc).__name__,
        )
        return WidgetErrorResult(
            label=widget.label,
            layout=widget.layout,
            loading=widget.loading,
        )


async def _load_eager_widgets(
    binding: DashboardBinding,
    request: Request,
    widgets: Iterable[WidgetDefinition],
) -> dict[str, WidgetResult]:
    semaphore = anyio.Semaphore(binding.dashboard.max_concurrent_widgets)
    results: dict[str, WidgetResult] = {}

    async def load(widget: WidgetDefinition) -> None:
        async with semaphore:
            results[str(widget.widget_id)] = await _execute_widget(
                binding,
                request,
                widget,
            )

    async with anyio.create_task_group() as group:
        for widget in widgets:
            group.start_soon(load, widget)
    return results


def _launcher_view(request: Request, launcher: LauncherItem) -> dict[str, object]:
    return {
        "label": launcher.label,
        "description": launcher.description,
        "path": mounted_path(request, launcher.path),
    }


def _widget_view(
    request: Request,
    widget: WidgetDefinition,
    result: WidgetResult | None,
) -> dict[str, object]:
    return {
        "definition": widget,
        "result": result,
        "widget_id": str(widget.widget_id),
        "widget_path": mounted_path(request, widget_path(str(widget.widget_id))),
        "is_lazy": widget.loading is WidgetLoadingMode.LAZY and result is None,
    }


def build_dashboard_routes(binding: DashboardBinding) -> list[Route]:
    async def dashboard_home(request: Request) -> Response:
        widgets = visible_widgets(binding, request)
        eager = tuple(widget for widget in widgets if widget.loading is WidgetLoadingMode.EAGER)
        results = await _load_eager_widgets(binding, request, eager)
        views = tuple(
            _widget_view(request, widget, results.get(str(widget.widget_id))) for widget in widgets
        )
        launchers = tuple(
            _launcher_view(request, launcher) for launcher in visible_launchers(binding, request)
        )
        return binding.templates.TemplateResponse(
            request,
            "dashboard/index.html",
            {
                "dashboard": binding.dashboard,
                "launchers": launchers,
                "widgets": views,
            },
            headers={"Cache-Control": "no-store"},
        )

    routes: list[Route] = [
        Route(
            "/",
            dashboard_home,
            methods=["GET"],
            name="rakit.dashboard",
        )
    ]

    for widget in binding.widgets:

        async def widget_fragment(
            request: Request,
            widget: WidgetDefinition = widget,
        ) -> Response:
            if not _allowed(binding, _principal(request), widget.permission):
                return PlainTextResponse(
                    "Forbidden",
                    status_code=403,
                    headers={"Cache-Control": "no-store"},
                )
            result = await _execute_widget(binding, request, widget)
            return binding.templates.TemplateResponse(
                request,
                "dashboard/_widget.html",
                {"widget": _widget_view(request, widget, result)},
                headers={"Cache-Control": "no-store"},
            )

        routes.append(
            Route(
                widget_path(str(widget.widget_id)),
                widget_fragment,
                methods=["GET"],
                name=f"rakit.dashboard.widget:{widget.widget_id}",
            )
        )

    return routes


__all__ = [
    "DashboardBinding",
    "build_dashboard_routes",
    "visible_launchers",
    "visible_widgets",
    "widget_path",
]
