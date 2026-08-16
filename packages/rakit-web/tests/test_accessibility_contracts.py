import re
from html.parser import HTMLParser

import httpx
import pytest


class _IdParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.ids: list[str] = []
        self.h1_count = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        if isinstance(attributes.get("id"), str):
            self.ids.append(attributes["id"])
        if tag == "h1":
            self.h1_count += 1


def _document_contract(html: str) -> _IdParser:
    parser = _IdParser()
    parser.feed(html)
    return parser


def _duplicate_ids(html: str) -> set[str]:
    parser = _document_contract(html)
    return {value for value in parser.ids if parser.ids.count(value) > 1}


@pytest.mark.anyio
async def test_dashboard_has_skip_link_landmarks_one_h1_and_live_announcer() -> None:
    from examples.dashboard.main import admin

    app = admin.asgi()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://localhost",
    ) as client:
        response = await client.get("/")

    document = _document_contract(response.text)
    assert response.status_code == 200
    assert '<a\n      href="#rakit-main-content"' in response.text
    assert '<main id="rakit-main-content"' in response.text
    assert '<nav ' in response.text
    assert document.h1_count == 1
    assert _duplicate_ids(response.text) == set()
    assert '<title>Operations dashboard' in response.text
    assert 'id="rakit-announcer"' in response.text
    assert 'role="status"' in response.text
    assert 'aria-live="polite"' in response.text


@pytest.mark.anyio
async def test_invalid_form_links_summary_fields_and_focus_target() -> None:
    from examples.fastapi_sqlalchemy import relationship_review

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=relationship_review.app),
        base_url="http://localhost",
    ) as client:
        response = await client.post(
            "/orders/new",
            data={
                "csrf_token": "csrf",
                "submission_token": "demo-submission-token",
            },
        )

    document = _document_contract(response.text)
    assert response.status_code == 422
    assert document.h1_count == 1
    assert _duplicate_ids(response.text) == set()
    assert 'aria-invalid="true"' in response.text
    assert re.search(r'aria-describedby="[^"]+"', response.text)
    assert 'data-rakit-focus-target="form-errors"' in response.text
    assert re.search(r'href="#rakit-[^"]+"', response.text)


@pytest.mark.anyio
async def test_sortable_table_uses_button_and_aria_sort() -> None:
    from examples.dashboard.main import admin

    app = admin.asgi()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://localhost",
    ) as client:
        response = await client.get("/orders?sort=id")

    assert response.status_code == 200
    header = re.search(
        r'<th[^>]*aria-sort="ascending"[^>]*>(.*?)</th>',
        response.text,
        flags=re.DOTALL,
    )
    assert header is not None
    assert '<button' in header.group(1)
    assert 'name="sort"' in header.group(1)
    assert 'aria-label="Sort by id' in header.group(1)


def test_progressive_enhancement_asset_declares_focus_restoration_and_htmx_focus() -> None:
    from importlib.resources import files

    script = files("rakit_web").joinpath("static", "rakit-ui.js").read_text()

    assert "data-rakit-focus-target" in script
    assert "rakitReturnFocus" in script
    assert 'htmx:afterSwap' in script
