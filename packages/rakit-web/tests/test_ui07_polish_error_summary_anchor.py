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


def test_relationship_validation_summary_anchor_targets_rendered_parent_status_field() -> None:
    identity = IdentityCodec().encode(RecordIdentity(values={"id": 1}))
    with TestClient(_fresh_showcase_app(), base_url="http://localhost") as client:
        _login(client)
        response = client.post(
            f"/relationship-states/{identity}/edit",
            data={
                "csrf_token": "csrf",
                "submission_token": "showcase-submission",
                "concurrency_token": "relationship-parent-token",
            },
            follow_redirects=False,
        )

    assert response.status_code == 422
    anchor = re.search(r'href="#([^"]+)">Parent status: This field is required\.</a>', response.text)
    assert anchor is not None
    assert f'id="{anchor.group(1)}"' in response.text
