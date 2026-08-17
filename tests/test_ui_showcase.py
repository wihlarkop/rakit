from starlette.testclient import TestClient


def _login(client: TestClient) -> None:
    page = client.get("/auth/login")
    assert page.status_code == 200
    login_csrf = page.cookies["rakit_login_csrf"]
    client.cookies.set("rakit_login_csrf", login_csrf)
    response = client.post(
        "/auth/login",
        data={
            "identifier": "operator@example.com",
            "password": "demo-password",
            "login_csrf_token": login_csrf,
        },
        follow_redirects=False,
    )
    assert response.status_code == 303
    client.cookies.set("rakit_session", response.cookies["rakit_session"])


def test_ui_showcase_exposes_dashboard_ui_lab_and_resources() -> None:
    from examples.ui_showcase.main import admin

    app = admin.asgi()
    with TestClient(app) as client:
        _login(client)
        dashboard = client.get("/")
        ui_lab = client.get("/ui-lab")
        orders = client.get("/orders")

    assert dashboard.status_code == 200
    assert ui_lab.status_code == 200
    assert orders.status_code == 200
    assert "Rakit Commerce" in dashboard.text
    assert "UI Lab" in ui_lab.text
