import re
from importlib.resources import files

import httpx
import pytest
from rakit import Admin


@pytest.mark.anyio
async def test_theme_script_is_local_and_csp_stays_strict() -> None:
    admin = Admin(title="Accessibility", debug=True)
    app = admin.asgi()

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://localhost",
    ) as client:
        response = await client.get("/")

    assert response.status_code == 200
    match = re.search(r'<script src="([^"]*theme\.[a-f0-9]{8}\.js)"', response.text)
    assert match is not None
    assert match.group(1).startswith("/_system/static/")
    csp = response.headers["content-security-policy"]
    assert "default-src 'self'" in csp
    assert "'unsafe-inline'" not in csp


@pytest.mark.anyio
async def test_htmx_indicator_styles_are_csp_safe() -> None:
    admin = Admin(title="Accessibility", debug=True)
    app = admin.asgi()

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://localhost",
    ) as client:
        response = await client.get("/")

    css = files("rakit_web").joinpath("static", "rakit.css").read_text()
    assert response.status_code == 200
    assert 'name="htmx-config"' in response.text
    assert '"includeIndicatorStyles": false' in response.text
    assert ".htmx-indicator" in css
    assert ".htmx-request .htmx-indicator" in css


@pytest.mark.anyio
async def test_theme_control_and_asset_support_light_dark_system() -> None:
    admin = Admin(title="Accessibility", debug=True)
    app = admin.asgi()

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://localhost",
    ) as client:
        response = await client.get("/")
        match = re.search(r'<script src="([^"]*theme\.[a-f0-9]{8}\.js)"', response.text)
        assert match is not None
        script = await client.get(match.group(1))
        css_match = re.search(
            r'<link rel="stylesheet" href="([^"]*rakit\.[a-f0-9]{8}\.css)"', response.text
        )
        assert css_match is not None
        css = await client.get(css_match.group(1))

    assert response.text.count("data-rakit-theme-control") == 2
    assert len(re.findall(r"\sdata-rakit-theme-trigger(?:\s|>)", response.text)) == 2
    assert response.text.count('aria-haspopup="menu"') == 2
    assert response.text.count('data-rakit-theme-option="system"') == 2
    assert response.text.count('data-rakit-theme-option="light"') == 2
    assert response.text.count('data-rakit-theme-option="dark"') == 2
    assert response.text.count('role="menuitemradio"') == 6
    assert "data-rakit-theme-select" not in response.text
    assert script.status_code == 200
    assert "localStorage" in script.text
    assert 'matchMedia("(prefers-color-scheme: dark)")' in script.text
    assert 'new Set(["light", "dark", "system"])' in script.text
    assert 'querySelectorAll("[data-rakit-theme-control]")' in script.text
    assert 'querySelectorAll("[data-rakit-theme-option]")' in script.text
    assert 'event.key === "Escape"' in script.text
    assert 'event.key === "ArrowDown"' in script.text
    assert css.status_code == 200
    assert "prefers-reduced-motion" in css.text
