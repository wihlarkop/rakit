from starlette.testclient import TestClient


def _showcase_client(app: object) -> TestClient:
    return TestClient(
        app,  # type: ignore[arg-type]
        base_url="http://localhost",
        client=("127.0.0.1", 50000),
    )


def _login(client: TestClient, *, password: str = "demo-password") -> object:
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


def test_ui_showcase_exposes_invalid_login_state() -> None:
    from examples.ui_showcase.main import admin

    app = admin.asgi()
    with _showcase_client(app) as client:
        response = _login(client, password="wrong-password")

    assert response.status_code == 401
    assert "Invalid credentials." in response.text
