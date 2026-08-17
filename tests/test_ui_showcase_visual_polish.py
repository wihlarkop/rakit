from pathlib import Path

UI_LAB_TEMPLATE = (
    Path(__file__).resolve().parents[1] / "examples" / "ui_showcase" / "templates" / "ui_lab.html"
)


def _ui_lab_source() -> str:
    return UI_LAB_TEMPLATE.read_text(encoding="utf-8")


def test_ui_lab_dialog_is_explicitly_centered_in_the_viewport() -> None:
    source = _ui_lab_source()

    assert 'class="rakit-dialog fixed inset-0 m-auto"' in source


def test_ui_lab_popover_host_does_not_clip_floating_content() -> None:
    source = _ui_lab_source()

    assert '<section class="rakit-panel overflow-visible">' in source
    assert '<header class="rakit-panel-header rounded-t-rakit-md">' in source
    assert 'class="rakit-popover"' in source


def test_ui_lab_page_size_uses_spaced_custom_chevron() -> None:
    source = _ui_lab_source()

    assert 'class="rakit-pagination-size appearance-none pl-3 pr-9"' in source
    assert 'rakit_icon("chevron-down"' in source
    assert "right-2.5" in source
    assert "pointer-events-none" in source
