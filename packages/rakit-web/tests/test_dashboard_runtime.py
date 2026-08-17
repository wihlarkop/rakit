import httpx
import pytest
from conftest import LifespanDriver
from rakit import (
    Admin,
    DashboardDefinition,
    LauncherItem,
    SecretValue,
    StatWidgetResult,
    WidgetContext,
    WidgetDefinition,
    WidgetLayout,
    WidgetLoadingMode,
)
from rakit_core.auth import Principal
from rakit_core.permissions import PermissionRequirement
from rakit_web.dashboard_routes import (
    DashboardBinding,
    visible_launchers,
    visible_widgets,
)
from rakit_web.resource_routes import build_templates
from starlette.requests import Request


def _admin() -> Admin:
    return Admin(
        admin_id="operations",
        title="Operations",
        debug=False,
        secret_key=SecretValue("x" * 32),
    )


@pytest.mark.anyio
async def test_root_renders_dashboard_shell() -> None:
    admin = _admin()
    app = admin.asgi()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://localhost",
    ) as client:
        response = await client.get("/")

    assert response.status_code == 200
    assert "<h1" in response.text
    assert "Operations" in response.text
    assert "Registered resources, pages, and widgets will appear here" in response.text
    assert 'href="#rakit-main-content"' in response.text
    assert 'aria-label="Primary navigation"' in response.text


@pytest.mark.anyio
async def test_dashboard_honors_semantic_widget_layout_without_inline_styles() -> None:
    admin = _admin()

    async def pending(_context: WidgetContext) -> StatWidgetResult:
        return StatWidgetResult(label="ignored", value=12)

    admin.register_widget(
        WidgetDefinition(
            widget_id="pending_orders",
            label="Pending orders",
            loader=pending,
            layout=WidgetLayout(size="small", min_height=120),
        )
    )
    admin.register_widget(
        WidgetDefinition(
            widget_id="revenue",
            label="Revenue",
            loader=pending,
            layout=WidgetLayout(size="large"),
        )
    )
    app = admin.asgi()

    async with (
        LifespanDriver(app),
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://localhost",
        ) as client,
    ):
        response = await client.get("/")

    assert response.status_code == 200
    assert 'class="grid grid-cols-1 items-start gap-4 md:grid-cols-12"' in response.text
    assert 'data-rakit-dashboard-widget-size="small"' in response.text
    assert "xl:col-span-3" in response.text
    assert 'data-rakit-dashboard-widget-min-height="120"' in response.text
    assert 'data-rakit-dashboard-widget-size="large"' in response.text
    assert "xl:col-span-9" in response.text
    assert "style=" not in response.text
    assert "hidden text-xs text-rakit-text-muted" in response.text
    assert "[.htmx-request&]:inline" in response.text
    assert 'hx-target="#rakit-dashboard-widget-pending_orders-content"' in response.text
    assert 'hx-select="#rakit-dashboard-widget-pending_orders-content"' in response.text
    assert 'hx-disabled-elt="this"' in response.text
    assert 'aria-live="polite"' in response.text


@pytest.mark.anyio
async def test_widget_failure_is_isolated() -> None:
    admin = _admin()

    async def pending(_context: WidgetContext) -> StatWidgetResult:
        return StatWidgetResult(label="ignored", value=12)

    async def broken(_context: WidgetContext) -> StatWidgetResult:
        raise RuntimeError("database unavailable")

    admin.register_widget(
        WidgetDefinition(
            widget_id="pending_orders",
            label="Pending orders",
            loader=pending,
        )
    )
    admin.register_widget(
        WidgetDefinition(
            widget_id="revenue",
            label="Revenue",
            loader=broken,
        )
    )
    app = admin.asgi()

    async with (
        LifespanDriver(app),
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://localhost",
        ) as client,
    ):
        response = await client.get("/")

    assert response.status_code == 200
    assert "Pending orders" in response.text
    assert ">12<" in response.text
    assert "Revenue" in response.text
    assert "Unable to load this widget." in response.text


@pytest.mark.anyio
async def test_lazy_widget_loads_through_fragment_endpoint() -> None:
    admin = _admin()

    async def pending(_context: WidgetContext) -> StatWidgetResult:
        return StatWidgetResult(label="ignored", value=7)

    admin.register_widget(
        WidgetDefinition(
            widget_id="pending_orders",
            label="Pending orders",
            loader=pending,
            loading=WidgetLoadingMode.LAZY,
        )
    )
    app = admin.asgi()

    async with (
        LifespanDriver(app),
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://localhost",
        ) as client,
    ):
        response = await client.get("/")
        fragment = await client.get("/_dashboard/widgets/pending_orders")

    assert response.status_code == 200
    assert 'hx-get="/_dashboard/widgets/pending_orders"' in response.text
    assert "Loading Pending orders" in response.text
    assert fragment.status_code == 200
    assert ">7<" in fragment.text
    assert 'aria-label="Refresh Pending orders"' in fragment.text


def test_dashboard_navigation_component_is_mount_aware() -> None:
    request = Request(
        {
            "type": "http",
            "http_version": "1.1",
            "method": "GET",
            "scheme": "http",
            "path": "/reports",
            "raw_path": b"/reports",
            "root_path": "/admin",
            "query_string": b"",
            "headers": [],
            "client": ("127.0.0.1", 1),
            "server": ("localhost", 80),
        }
    )
    template = build_templates(()).env.get_template("components/dashboard_navigation.html")
    rendered = template.render(request=request)

    assert 'href="/admin/"' in rendered
    assert "Dashboard" in rendered
    assert 'data-rakit-breadcrumb="page"' in rendered
    assert 'aria-label="Breadcrumb"' in rendered


def test_forbidden_launchers_and_widgets_are_hidden() -> None:
    allowed = PermissionRequirement.all_of("operations.dashboard.allowed")
    forbidden = PermissionRequirement.all_of("operations.dashboard.forbidden")
    dashboard = DashboardDefinition(
        dashboard_id="main",
        title="Operations",
        widgets=("allowed_widget", "forbidden_widget"),
        launchers=(
            LauncherItem(
                launcher_id="orders",
                label="Orders",
                path="/orders",
                permission=allowed,
            ),
            LauncherItem(
                launcher_id="security",
                label="Security Settings",
                path="/security",
                permission=forbidden,
            ),
        ),
    )

    def result(_context: WidgetContext) -> StatWidgetResult:
        return StatWidgetResult(label="ignored", value=1)

    binding = DashboardBinding(
        dashboard=dashboard,
        resources=(),
        pages=(),
        widgets=(
            WidgetDefinition(
                widget_id="allowed_widget",
                label="Allowed",
                loader=result,
                permission=allowed,
            ),
            WidgetDefinition(
                widget_id="forbidden_widget",
                label="Forbidden",
                loader=result,
                permission=forbidden,
            ),
        ),
        templates=build_templates(()),
        admin_id="operations",
        auth_enabled=True,
        superuser_bypass=True,
    )
    principal = Principal(
        subject_id="user-1",
        authenticated=True,
        permissions=frozenset({"operations.dashboard.allowed"}),
    )
    request = Request(
        {
            "type": "http",
            "http_version": "1.1",
            "method": "GET",
            "scheme": "http",
            "path": "/",
            "raw_path": b"/",
            "query_string": b"",
            "headers": [],
            "client": ("127.0.0.1", 1),
            "server": ("localhost", 80),
            "state": {"principal": principal},
        }
    )

    assert [item.label for item in visible_launchers(binding, request)] == ["Orders"]
    assert [item.label for item in visible_widgets(binding, request)] == ["Allowed"]
