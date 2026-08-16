import re

import httpx
import pytest
from rakit import Admin

# These contracts intentionally precede the 10C theme implementation.


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
    assert "script-src 'self'" in csp
    assert "'unsafe-inline'" not in csp


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

    assert 'for="rakit-theme-select"' in response.text
    assert "data-rakit-theme-select" in response.text
    assert '<option value="system">System</option>' in response.text
    assert '<option value="light">Light</option>' in response.text
    assert '<option value="dark">Dark</option>' in response.text
    assert script.status_code == 200
    assert "localStorage" in script.text
    assert 'matchMedia("(prefers-color-scheme: dark)")' in script.text
    assert 'new Set(["light", "dark", "system"])' in script.text
    assert css.status_code == 200
    assert "prefers-reduced-motion" in css.text
