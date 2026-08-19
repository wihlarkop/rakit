import importlib

from rakit_core.identity import IdentityCodec, RecordIdentity
from starlette.testclient import TestClient


def _fresh_showcase_app():
    from examples.ui_showcase import main as showcase

    return importlib.reload(showcase).admin.asgi()


def _login(client: TestClient) -> None:
    page = client.get("/auth/login")
    assert page.status_code == 200
    response = client.post(
        "/auth/login",
        data={
            "identifier": "operator@example.com",
            "password": "demo-password",
            "login_csrf_token": page.cookies["rakit_login_csrf"],
        },
        follow_redirects=False,
    )
    assert response.status_code == 303


def test_relationship_edit_renders_required_parent_status_error_target() -> None:
    identity = IdentityCodec().encode(RecordIdentity(values={"id": 1}))
    with TestClient(
        _fresh_showcase_app(),
        base_url="http://localhost",
        client=("127.0.0.1", 50000),
    ) as client:
        _login(client)
        form = client.get(f"/relationship-states/{identity}/edit")

    assert form.status_code == 200
    assert "Parent status" in form.text
    assert 'name="status"' in form.text
    assert 'id="rakit-relationship_states-status"' in form.text
