from __future__ import annotations

import importlib

from httpx import Response
from rakit_core.identity import IdentityCodec, RecordIdentity
from rakit_web.field_presentation import Autocomplete, MultiAutocomplete
from starlette.testclient import TestClient

from examples.ui_showcase import main as showcase
from examples.ui_showcase.advanced_states import RELATIONSHIPS


def _client() -> TestClient:
    module = importlib.reload(showcase)
    return TestClient(
        module.admin.asgi(),
        base_url="http://localhost",
        client=("127.0.0.1", 50000),
    )


def _login(client: TestClient) -> Response:
    page = client.get("/auth/login")
    assert page.status_code == 200
    csrf = page.cookies["rakit_login_csrf"]
    return client.post(
        "/auth/login",
        data={
            "identifier": "operator@example.com",
            "password": "demo-password",
            "login_csrf_token": csrf,
        },
        follow_redirects=False,
    )


def _parent_identity() -> str:
    return IdentityCodec().encode(RecordIdentity(values={"id": 1}))


def test_showcase_relationships_use_typed_single_and_multi_autocomplete() -> None:
    by_id = {str(item.relationship_id): item for item in RELATIONSHIPS}
    assert isinstance(by_id["customer"].presentation, Autocomplete)
    assert not isinstance(by_id["customer"].presentation, MultiAutocomplete)
    assert isinstance(by_id["tags"].presentation, MultiAutocomplete)
    assert isinstance(by_id["participants"].presentation, MultiAutocomplete)
    assert by_id["participants"].presentation.page_size == 10


def test_relationship_edit_page_renders_enhanced_comboboxes_with_native_fallbacks() -> None:
    with _client() as client:
        assert _login(client).status_code == 303
        response = client.get(f"/relationship-states/{_parent_identity()}/edit")

    assert response.status_code == 200
    html = response.text
    assert 'data-rakit-widget="autocomplete"' in html
    assert 'data-rakit-widget="multi_autocomplete"' in html
    assert 'role="combobox"' in html
    assert 'aria-autocomplete="list"' in html
    assert 'aria-expanded="false"' in html
    assert "data-rakit-autocomplete-fallback" in html
    assert ">Browse</a>" in html
    assert "Search customer..." in html
    assert "Add participants..." in html


def test_remote_candidate_helper_is_permission_scoped_bounded_and_canonical() -> None:
    parent = _parent_identity()
    with _client() as client:
        assert _login(client).status_code == 303
        customer = client.get(
            f"/relationship-states/{parent}/_relationships/customer/options",
            params={"q": "Person", "page": "1"},
        )
        participants = client.get(
            f"/relationship-states/{parent}/_relationships/participants/options",
            params={"q": "Person", "page": "1"},
        )

    assert customer.status_code == 200
    assert customer.headers["cache-control"] == "no-store"
    assert customer.text.count("data-rakit-option ") <= 12
    assert 'data-rakit-option-identity="' in customer.text
    assert "Person 01" in customer.text

    assert participants.status_code == 200
    assert participants.text.count("data-rakit-option ") <= 10
    assert 'data-rakit-has-more="true"' in participants.text
    assert 'data-rakit-next-page="2"' in participants.text


def test_candidate_helper_rejects_unauthenticated_access() -> None:
    parent = _parent_identity()
    with _client() as client:
        response = client.get(
            f"/relationship-states/{parent}/_relationships/customer/options",
            params={"q": "Person"},
            follow_redirects=False,
        )

    assert response.status_code in {303, 401, 403}
    assert "data-rakit-option" not in response.text


def test_no_javascript_picker_is_searchable_bounded_and_returns_canonical_selection() -> None:
    parent = _parent_identity()
    with _client() as client:
        assert _login(client).status_code == 303
        response = client.get(
            f"/relationship-states/{parent}/_relationships/participants/picker",
            params={"q": "Person", "page": "1"},
        )

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    html = response.text
    assert "Relationship picker" in html
    assert 'name="q" type="search"' in html
    assert html.count('type="checkbox"') <= 10
    assert 'name="__rakit_rel__participants__link__' in html
    assert 'action="/relationship-states/' in html
    assert "/edit" in html
