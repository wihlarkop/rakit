from httpx import Response
from rakit.core import IdentityCodec, RecordIdentity
from starlette.testclient import TestClient
from starlette.types import ASGIApp


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
    from examples.ui_showcase.main import admin

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
        orders_page_two = client.get("/orders", params={"per_page": "5", "page": "2"})

    assert dashboard.status_code == 200
    assert "Rakit Commerce" in dashboard.text
    assert "Commerce operations" in dashboard.text
    for path in resources:
        assert f'href="/{path}"' in dashboard.text

    assert ui_lab.status_code == 200
    for section in (
        "Typography",
        "Buttons",
        "Fields",
        "Status",
        "Feedback",
        "Tables",
        "Relationships",
        "Empty states",
        "Loading states",
        "Errors",
        "Theme",
    ):
        assert section in ui_lab.text

    assert all(response.status_code == 200 for response in resources.values())
    assert "Atlas Research &amp; Engineering Cooperative" in resources["customers"].text
    assert "Precision mechanical keyboard" in resources["products"].text
    assert "ORD-1080" in resources["orders"].text
    assert "Workspace" in resources["categories"].text
    assert "Low stock" in resources["inventory"].text
    assert "Commerce operations" in resources["teams"].text

    assert orders_page_two.status_code == 200
    assert "ORD-1075" in orders_page_two.text
    assert "Page 2" in orders_page_two.text


def test_ui_showcase_uses_dashboard_shell_with_mobile_drawer() -> None:
    from examples.ui_showcase.main import admin

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


def test_ui_showcase_exposes_record_confirmation_action_and_relationship_contracts() -> None:
    from examples.ui_showcase.main import admin

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
    assert "This change is applied only when you confirm and submit." in refund.text

    relationship_ids = {
        str(entry.definition.relationship_id)
        for entry in admin.compiled.relationships
        if entry.source_resource_id == "orders"
    }
    assert {"customer", "products"} <= relationship_ids


def test_ui_showcase_exposes_invalid_login_state() -> None:
    from examples.ui_showcase.main import admin

    app = admin.asgi()
    with _showcase_client(app) as client:
        response = _login(client, password="wrong-password")

    assert response.status_code == 401
    assert "Invalid credentials." in response.text


def test_ui_showcase_login_page_does_not_render_admin_shell() -> None:
    from examples.ui_showcase.main import admin

    app = admin.asgi()
    with _showcase_client(app) as client:
        response = client.get("/auth/login")

    assert response.status_code == 200
    assert "data-rakit-app-shell" not in response.text
    assert "data-rakit-desktop-navigation" not in response.text
    assert "data-rakit-mobile-navigation-trigger" not in response.text


def test_ui_showcase_login_csrf_survives_browser_favicon_redirect() -> None:
    from examples.ui_showcase.main import admin

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
