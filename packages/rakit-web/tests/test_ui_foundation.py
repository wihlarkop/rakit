import re
from importlib.resources import files

import httpx
import pytest
from rakit import Admin
from rakit_web.resource_routes import build_templates


def _css_block_end(css: str, marker: str) -> int:
    start = css.index(marker)
    opening = css.index("{", start)
    depth = 0
    for index in range(opening, len(css)):
        if css[index] == "{":
            depth += 1
        elif css[index] == "}":
            depth -= 1
            if depth == 0:
                return index
    raise AssertionError(f"Unclosed CSS block for {marker!r}")


def test_ui_foundation_defines_semantic_tailwind_roles() -> None:
    css = files("rakit_web").joinpath("assets", "rakit.css").read_text()

    for token in (
        "--color-rakit-brand-50:",
        "--color-rakit-brand-600:",
        "--color-rakit-bg:",
        "--color-rakit-surface:",
        "--color-rakit-surface-subtle:",
        "--color-rakit-surface-raised:",
        "--color-rakit-border:",
        "--color-rakit-border-strong:",
        "--color-rakit-text:",
        "--color-rakit-text-muted:",
        "--color-rakit-success:",
        "--color-rakit-warning:",
        "--color-rakit-danger:",
        "--color-rakit-info:",
        "--color-rakit-focus:",
        "--radius-rakit-sm:",
        "--radius-rakit-md:",
        "--shadow-rakit-sm:",
    ):
        assert token in css

    assert css.count("oklch(") >= 20


def test_collapsed_sidebar_state_overrides_tailwind_utility_layer() -> None:
    css = files("rakit_web").joinpath("assets", "rakit.css").read_text()
    components_end = _css_block_end(css, "@layer components")
    collapsed_rule = (
        "[data-rakit-desktop-navigation][data-rakit-desktop-navigation-collapsed] {"
    )

    assert css.index(collapsed_rule) > components_end
    assert "width: 4.5rem;" in css[css.index(collapsed_rule) :]


def test_lucide_icon_helper_is_allowlisted_and_registered_with_jinja() -> None:
    from rakit_web.icons import render_icon

    templates = build_templates(())
    assert templates.env.globals["rakit_icon"] is render_icon

    icon = str(
        render_icon(
            "moon",
            class_name='size-5" data-bad="value',
        )
    )
    assert icon.startswith("<svg")
    assert 'viewBox="0 0 24 24"' in icon
    assert 'aria-hidden="true"' in icon
    assert 'focusable="false"' in icon
    assert "&quot; data-bad=&quot;value" in icon

    with pytest.raises(ValueError, match="Unknown Rakit icon"):
        render_icon("not-a-real-icon")


def test_lucide_license_notice_is_packaged_with_rakit_web() -> None:
    notice = files("rakit_web").joinpath("vendor", "lucide", "LICENSE.txt").read_text()
    assert "ISC License" in notice
    assert "Lucide Icons and Contributors" in notice
    assert "The MIT License (MIT)" in notice
    assert "Cole Bemis" in notice


@pytest.mark.anyio
async def test_shell_uses_icon_navigation_and_accessible_theme_popovers() -> None:
    admin = Admin(title="Foundation", debug=True)
    app = admin.asgi()

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://localhost",
    ) as client:
        response = await client.get("/")
        theme_script_path = response.text.split('src="', 1)[1].split('"', 1)[0]
        theme_script = await client.get(theme_script_path)

    assert response.status_code == 200
    assert response.text.count("data-rakit-theme-control") == 2
    assert len(re.findall(r"\sdata-rakit-theme-trigger(?:\s|>)", response.text)) == 2
    assert response.text.count('aria-haspopup="menu"') == 2
    assert response.text.count("data-rakit-theme-menu") == 2
    assert response.text.count('data-rakit-theme-option="system"') == 2
    assert response.text.count('data-rakit-theme-option="light"') == 2
    assert response.text.count('data-rakit-theme-option="dark"') == 2
    assert response.text.count('role="menuitemradio"') == 6
    assert "data-rakit-theme-select" not in response.text
    assert 'data-rakit-navigation-icon="dashboard"' in response.text
    assert (
        'data-rakit-navigation-icon="resource"' in response.text or "Resources" not in response.text
    )
    assert '<svg aria-hidden="true"' in response.text

    assert theme_script.status_code == 200
    assert 'querySelectorAll("[data-rakit-theme-control]")' in theme_script.text
    assert 'querySelectorAll("[data-rakit-theme-option]")' in theme_script.text
    assert 'event.key === "Escape"' in theme_script.text
    assert 'event.key === "ArrowDown"' in theme_script.text
    assert "localStorage.setItem(RAKIT_THEME_KEY, preference)" in theme_script.text
