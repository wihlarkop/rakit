import importlib
import re

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


def _hidden_value(html: str, name: str) -> str:
    match = re.search(rf'<input type="hidden" name="{name}" value="([^"]*)"', html)
    assert match is not None
    return match.group(1)


def test_relationship_validation_summary_anchor_targets_rendered_parent_status_field() -> None:
    identity = IdentityCodec().encode(RecordIdentity(values={"id": 1}))
    edit_path = f"/relationship-states/{identity}/edit"
    with TestClient(
        _fresh_showcase_app(),
        base_url="http://localhost",
        client=("127.0.0.1", 50000),
    ) as client:
        _login(client)
        form = client.get(edit_path)
        assert form.status_code == 200
        response = client.post(
            edit_path,
            data={
                "csrf_token": _hidden_value(form.text, "csrf_token"),
                "submission_token": _hidden_value(form.text, "submission_token"),
                "concurrency_token": _hidden_value(form.text, "concurrency_token"),
            },
            follow_redirects=False,
        )

    assert response.status_code == 422
    anchor = re.search(
        r'href="#([^"]+)">Parent status: This field is required\.</a>',
        response.text,
    )
    assert anchor is not None
    assert f'id="{anchor.group(1)}"' in response.text
