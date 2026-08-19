from importlib.resources import files


def test_desktop_sidebar_scroll_position_is_persisted_per_tab_and_mount() -> None:
    package = files("rakit_web")
    template = package.joinpath("templates", "components", "admin_navigation.html").read_text()
    shell = package.joinpath("static", "rakit-shell.js").read_text()

    assert "data-rakit-desktop-navigation-scroll" in template
    assert 'data-rakit-navigation-scroll-key="{{ navigation.dashboard.path }}"' in template

    assert 'const RAKIT_SIDEBAR_SCROLL_KEY_PREFIX = "rakit.sidebar.scroll";' in shell
    assert "sessionStorage.setItem(" in shell
    assert "sessionStorage.getItem(" in shell
    assert "navigation.scrollTop" in shell
    assert "navigation.scrollHeight - navigation.clientHeight" in shell
    assert 'window.addEventListener("pagehide", rakitStoreDesktopNavigationScroll);' in shell
    assert "requestAnimationFrame(rakitRestoreDesktopNavigationScroll);" in shell
