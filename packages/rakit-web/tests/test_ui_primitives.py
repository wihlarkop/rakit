from importlib.resources import files
from typing import Any

from rakit_web.resource_routes import build_templates


def _ui_module() -> Any:
    return build_templates(()).env.get_template("components/ui.html").module


def test_button_variants_disabled_and_loading_are_semantic() -> None:
    ui = _ui_module()
    rendered = "".join(
        (
            str(ui.button("Save")),
            str(ui.button("Cancel", variant="secondary")),
            str(ui.button("Delete", variant="danger", disabled=True)),
            str(ui.button("Publish", loading=True)),
        )
    )

    assert 'class="rakit-button"' in rendered
    assert "rakit-button-secondary" in rendered
    assert "rakit-button-danger" in rendered
    assert "disabled" in rendered
    assert 'aria-busy="true"' in rendered
    assert "rakit-spinner" in rendered
    assert "<span>Publish</span>" in rendered


def test_icon_button_has_accessible_name_and_decorative_icon() -> None:
    ui = _ui_module()
    rendered = str(ui.icon_button("x", "Close dialog"))

    assert 'class="rakit-icon-button"' in rendered
    assert 'aria-label="Close dialog"' in rendered
    assert '<svg aria-hidden="true"' in rendered
    assert 'focusable="false"' in rendered


def test_status_and_alert_variants_keep_text_and_role_semantics() -> None:
    ui = _ui_module()
    rendered = "".join(
        (
            str(ui.status("Archived")),
            str(ui.status("Published", variant="success")),
            str(ui.status("Pending review", variant="warning")),
            str(ui.status("Failed", variant="danger")),
            str(ui.status("Syncing", variant="info")),
            str(ui.alert("Changes saved", variant="success")),
            str(ui.alert("Unable to save", variant="danger", urgent=True)),
        )
    )

    for variant in ("neutral", "success", "warning", "danger", "info"):
        assert f"rakit-status-{variant}" in rendered
    assert "Published" in rendered
    assert "Pending review" in rendered
    assert 'role="status"' in rendered
    assert 'role="alert"' in rendered


def test_loading_macro_keeps_readable_context() -> None:
    ui = _ui_module()
    rendered = str(ui.loading("Loading orders"))

    assert 'class="rakit-loading"' in rendered
    assert "rakit-spinner" in rendered
    assert "Loading orders" in rendered
    assert 'role="status"' in rendered


def test_field_primitives_cover_textarea_choice_file_and_states() -> None:
    css = files("rakit_web").joinpath("assets", "rakit.css").read_text()

    for marker in (
        ".rakit-textarea",
        ".rakit-checkbox",
        ".rakit-radio",
        ".rakit-file-input",
        ".rakit-field-help",
        ".rakit-field-required",
        '[aria-invalid="true"]',
        ":read-only",
        ":disabled",
    ):
        assert marker in css

    assert "accent-color: var(--color-rakit-brand-600);" in css
    assert ".rakit-file-input::file-selector-button" in css


def test_dialog_popover_and_loading_css_use_reusable_primitives() -> None:
    css = files("rakit_web").joinpath("assets", "rakit.css").read_text()

    for selector in (
        ".rakit-dialog-title",
        ".rakit-dialog-description",
        ".rakit-dialog-body",
        ".rakit-dialog-footer",
        ".rakit-popover",
        ".rakit-loading",
        ".rakit-spinner",
        "@keyframes rakit-spin",
    ):
        assert selector in css


def test_generic_dialog_and_details_popover_are_progressively_enhanced() -> None:
    script = files("rakit_web").joinpath("static", "rakit-ui.js").read_text()

    for marker in (
        "data-rakit-dialog-trigger",
        "data-rakit-dialog-close",
        "data-rakit-dialog-initial-focus",
        "data-rakit-dialog-backdrop-close",
        "rakitGenericDialogReturnFocus",
        "dialog.showModal()",
        'document.querySelectorAll("details[open]")',
        'event.key !== "Escape"',
        "restoreFocus: true",
    ):
        assert marker in script


def test_pagination_macro_marks_current_disabled_and_ellipsis_states() -> None:
    ui = _ui_module()
    items = [
        {"label": "Previous", "disabled": True},
        {"label": "1", "href": "?page=1", "current": True},
        {"label": "2", "href": "?page=2"},
        {"ellipsis": True},
        {"label": "Next", "href": "?page=2"},
    ]
    rendered = str(ui.pagination(items, aria_label="Example pages"))

    assert 'class="rakit-pagination"' in rendered
    assert 'aria-label="Example pages"' in rendered
    assert 'aria-disabled="true"' in rendered
    assert 'aria-current="page"' in rendered
    assert "rakit-pagination-current" in rendered
    assert "rakit-pagination-ellipsis" in rendered
    assert "?page=2" in rendered


def test_panel_header_uses_semantic_rakit_text_roles() -> None:
    ui = _ui_module()
    rendered = str(ui.panel_header("Inventory", "12 records"))

    assert "text-rakit-text" in rendered
    assert "text-rakit-text-muted" in rendered
    assert "text-slate-" not in rendered
