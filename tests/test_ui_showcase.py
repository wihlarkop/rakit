import importlib
import re

from httpx import Response
from rakit import Admin
from rakit.core import IdentityCodec, RecordIdentity
from starlette.testclient import TestClient
from starlette.types import ASGIApp


def _fresh_showcase_admin() -> Admin:
    from examples.ui_showcase import main as showcase

    return importlib.reload(showcase).admin


def _showcase_client(app: ASGIApp) -> TestClient:
    return TestClient(
        app,
        base_url="http://localhost",
        client=("127.0.0.1", 50000),
    )


def _login(client: TestClient, *, password: str = "demo-password") -> Response:
    page = client.get("/auth/login")
    assert page.status_code == 200
    login_csrf = page.cookies["rakit_login_csrf"]
    return client.post(
        "/auth/login",
        data={
            "identifier": "operator@example.com",
            "password": password,
            "login_csrf_token": login_csrf,
        },
        follow_redirects=False,
    )


def test_ui_showcase_exposes_realistic_application_and_ui_lab() -> None:
    admin = _fresh_showcase_admin()
    app = admin.asgi()
    with _showcase_client(app) as client:
        login = _login(client)
        assert login.status_code == 303

        dashboard = client.get("/")
        ui_lab = client.get("/ui-lab")
        resources = {
            "customers": client.get("/customers"),
            "products": client.get("/products"),
            "orders": client.get("/orders"),
            "categories": client.get("/categories"),
            "inventory": client.get("/inventory"),
            "teams": client.get("/teams"),
        }
        orders_page_two = client.get("/orders", params={"per_page": "20", "page": "2"})

    assert dashboard.status_code == 200
    assert "Rakit Commerce" in dashboard.text
    assert "Commerce operations" in dashboard.text
    for path in resources:
        assert f'href="/{path}"' in dashboard.text

    assert ui_lab.status_code == 200
    for section in (
        "Typography",
        "Iconography",
        "Buttons",
        "Fields",
        "Status",
        "Feedback",
        "Dialog and popover",
        "Pagination",
        "Tables",
        "Relationships",
        "Empty states",
        "Loading states",
        "Errors",
        "Theme",
    ):
        assert section in ui_lab.text
    assert "rakit-status-success" in ui_lab.text
    assert ">Published</span>" in ui_lab.text
    assert 'class="rakit-chip rakit-chip-relationship"' in ui_lab.text

    assert all(response.status_code == 200 for response in resources.values())
    assert "Atlas Research &amp; Engineering Cooperative" in resources["customers"].text
    assert "Precision mechanical keyboard" in resources["products"].text
    assert "ORD-1080" in resources["orders"].text
    assert "Workspace" in resources["categories"].text
    assert "Low stock" in resources["inventory"].text
    assert "Commerce operations" in resources["teams"].text

    assert 'data-rakit-filter-group="status"' in resources["orders"].text
    assert ">Paid</span>" in resources["orders"].text
    assert ">Pending review</span>" in resources["orders"].text
    assert '<option value="20" selected>20</option>' in resources["orders"].text
    assert '<option value="40">40</option>' in resources["orders"].text
    assert '<option value="80">80</option>' in resources["orders"].text
    assert 'data-rakit-filter-group="stock_level"' in resources["inventory"].text
    assert ">Needs attention</span>" in resources["inventory"].text

    products = resources["products"].text
    for filter_id in ("category", "status", "name", "sku", "price"):
        assert f'data-rakit-filter-group="{filter_id}"' in products
    assert "Show 5 more" in products
    assert "Ergonomic workspace accessories" in products
    assert "data-rakit-filter-rail" in products
    assert "data-rakit-filter-mobile-fallback" in products
    assert "data-rakit-filter-drawer" in products

    assert orders_page_two.status_code == 200
    assert "ORD-1060" in orders_page_two.text
    assert 'aria-current="page">2</a>' in orders_page_two.text


def test_ui_showcase_exposes_core_component_matrix() -> None:
    admin = _fresh_showcase_admin()
    app = admin.asgi()
    with _showcase_client(app) as client:
        login = _login(client)
        assert login.status_code == 303
        ui_lab = client.get("/ui-lab")

    assert ui_lab.status_code == 200
    for marker in (
        "rakit-button-secondary",
        "rakit-button-quiet",
        "rakit-button-danger",
        'aria-busy="true"',
        "rakit-icon-button",
        "rakit-textarea",
        "rakit-checkbox",
        "rakit-radio",
        "rakit-file-input",
        "rakit-field-help",
        "rakit-field-required",
        'aria-invalid="true"',
        "rakit-status-neutral",
        "rakit-status-success",
        "rakit-status-warning",
        "rakit-status-danger",
        "rakit-status-info",
        "rakit-alert-neutral",
        "rakit-alert-success",
        "rakit-alert-warning",
        "rakit-alert-danger",
        "rakit-alert-info",
        "data-rakit-dialog-trigger",
        "data-rakit-dialog",
        'aria-labelledby="ui-lab-dialog-title"',
        'aria-describedby="ui-lab-dialog-description"',
        "rakit-popover",
        "rakit-pagination",
        'aria-current="page"',
        'aria-disabled="true"',
        "rakit-pagination-size",
        "rakit-loading",
        "rakit-spinner",
    ):
        assert marker in ui_lab.text


def test_ui_showcase_uses_dashboard_shell_with_mobile_drawer() -> None:
    admin = _fresh_showcase_admin()
    app = admin.asgi()
    with _showcase_client(app) as client:
        login = _login(client)
        assert login.status_code == 303
        dashboard = client.get("/")
        orders = client.get("/orders")

    assert dashboard.status_code == 200
    assert "data-rakit-app-shell" in dashboard.text
    assert "data-rakit-desktop-navigation" in dashboard.text
    assert "data-rakit-mobile-navigation-trigger" in dashboard.text
    assert 'aria-controls="rakit-mobile-navigation"' in dashboard.text
    assert 'aria-expanded="false"' in dashboard.text
    assert 'id="rakit-mobile-navigation"' in dashboard.text
    assert "data-rakit-mobile-navigation" in dashboard.text
    assert "data-rakit-mobile-navigation-close" in dashboard.text
    assert 'aria-label="Open navigation"' in dashboard.text
    assert 'aria-label="Close navigation"' in dashboard.text
    assert 'class="overflow-x-auto border-b border-slate-200' not in dashboard.text
    assert 'aria-label="Primary navigation fallback"' in dashboard.text

    assert orders.status_code == 200
    assert 'href="/orders"' in orders.text
    assert 'aria-current="page"' in orders.text


def test_ui_showcase_uses_breadcrumbs_collapsible_sidebar_and_entity_detail_header() -> None:
    admin = _fresh_showcase_admin()
    app = admin.asgi()
    product_identity = IdentityCodec().encode(RecordIdentity(values={"id": "PRD-101"}))
    with _showcase_client(app) as client:
        login = _login(client)
        assert login.status_code == 303
        dashboard = client.get("/")
        ui_lab = client.get("/ui-lab")
        product = client.get(f"/products/{product_identity}")

        shell_match = re.search(
            r'<script src="([^"]*rakit-shell\.[a-f0-9]{8}\.js)"', dashboard.text
        )
        assert shell_match is not None
        shell_script = client.get(shell_match.group(1))

    assert dashboard.status_code == 200
    assert "data-rakit-desktop-navigation-toggle" in dashboard.text
    assert "data-rakit-sidebar-expanded-icon" in dashboard.text
    assert "data-rakit-sidebar-collapsed-icon" in dashboard.text
    assert 'aria-label="Collapse sidebar"' in dashboard.text

    assert shell_script.status_code == 200
    assert '"rakit.sidebar.collapsed"' in shell_script.text
    assert "data-rakit-desktop-navigation-collapsed" in shell_script.text
    assert "localStorage.setItem" in shell_script.text

    assert ui_lab.status_code == 200
    assert 'data-rakit-breadcrumb="page"' in ui_lab.text
    assert "data-rakit-breadcrumb-separator" in ui_lab.text
    assert 'aria-current="page">UI Lab</span>' in ui_lab.text

    assert product.status_code == 200
    assert 'data-rakit-breadcrumb="resource-detail"' in product.text
    assert 'aria-current="page">PRD-101</span>' in product.text
    expected_record_title = (
        "data-rakit-record-title>Precision mechanical keyboard with "
        "low-profile tactile switches</h1>"
    )
    assert expected_record_title in product.text
    assert "data-rakit-record-context>Product · PRD-101</p>" in product.text
    assert ">Product</h1>" not in product.text


def test_ui_showcase_exposes_record_confirmation_action_and_relationship_contracts() -> None:
    admin = _fresh_showcase_admin()
    app = admin.asgi()
    assert admin.compiled is not None
    identity = IdentityCodec().encode(RecordIdentity(values={"id": "ORD-1080"}))
    with _showcase_client(app) as client:
        login = _login(client)
        assert login.status_code == 303
        refund = client.get(f"/orders/{identity}/_actions/refund_order")

    assert refund.status_code == 200
    assert "Refund order" in refund.text
    assert "Impact" in refund.text
    assert "marked as potentially destructive" in refund.text
    assert "runs only when you confirm and submit" in refund.text

    relationship_ids = {
        str(entry.definition.relationship_id)
        for entry in admin.compiled.relationships
        if entry.source_resource_id == "orders"
    }
    assert {"customer", "products"} <= relationship_ids


def test_ui_showcase_exposes_invalid_login_state() -> None:
    admin = _fresh_showcase_admin()
    app = admin.asgi()
    with _showcase_client(app) as client:
        response = _login(client, password="wrong-password")

    assert response.status_code == 401
    assert "Invalid credentials." in response.text


def test_ui_showcase_login_page_does_not_render_admin_shell() -> None:
    admin = _fresh_showcase_admin()
    app = admin.asgi()
    with _showcase_client(app) as client:
        response = client.get("/auth/login")

    assert response.status_code == 200
    assert "data-rakit-app-shell" not in response.text
    assert "data-rakit-desktop-navigation" not in response.text
    assert "data-rakit-mobile-navigation-trigger" not in response.text


def test_ui_showcase_login_csrf_survives_browser_favicon_redirect() -> None:
    admin = _fresh_showcase_admin()
    app = admin.asgi()
    with _showcase_client(app) as client:
        login_page = client.get("/auth/login")
        assert login_page.status_code == 200
        original_csrf = login_page.cookies["rakit_login_csrf"]

        favicon = client.get("/favicon.ico", follow_redirects=True)
        assert favicon.status_code == 200
        assert favicon.url.path == "/auth/login"

        response = client.post(
            "/auth/login",
            data={
                "identifier": "operator@example.com",
                "password": "demo-password",
                "login_csrf_token": original_csrf,
            },
            follow_redirects=False,
        )

    assert response.status_code == 303
