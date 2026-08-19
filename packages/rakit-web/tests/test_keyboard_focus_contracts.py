from importlib.resources import files


def _read(*parts: str) -> str:
    return files("rakit_web").joinpath(*parts).read_text()


def test_overlay_focus_restoration_avoids_scroll_jumps() -> None:
    shell = _read("static", "rakit-shell.js")
    ui = _read("static", "rakit-ui.js")

    assert (
        'navigation.querySelector("[data-rakit-mobile-navigation-close]")?.focus({ '
        "preventScroll: true });"
    ) in shell
    assert "returnFocus.focus({ preventScroll: true });" in shell

    assert "target.focus({ preventScroll: true });" in ui
    assert "returnFocus.focus({ preventScroll: true });" in ui
    assert "initialFocus.focus({ preventScroll: true });" in ui
    assert "summary.focus({ preventScroll: true });" in ui
    assert (
        'dialog.querySelector("[data-rakit-confirm-preview]")?.focus({ preventScroll: true });'
        in ui
    )

    # Focus-target navigation is intentionally different: validation/HTMX feedback
    # still scrolls the newly focused target into the nearest visible region.
    assert 'focusTarget.scrollIntoView({ block: "nearest" });' in ui


def test_filter_disclosure_state_and_focus_are_synchronized() -> None:
    table = _read("templates", "resources", "_table.html")
    ui = _read("static", "rakit-ui.js")

    assert 'data-rakit-filter-drawer-trigger' in table
    assert 'aria-haspopup="dialog"' in table
    assert 'data-rakit-filter-rail-show' in table
    assert 'aria-expanded="false"' in table
    assert 'data-rakit-filter-rail-hide aria-controls="rakit-filter-rail-' in table
    assert 'aria-expanded="true">Hide</button>' in table

    assert 'show.setAttribute("aria-expanded", visible ? "true" : "false")' in ui
    assert 'hide.setAttribute("aria-expanded", visible ? "true" : "false")' in ui
    assert (
        'root.querySelector("[data-rakit-filter-rail-show]")?.focus({ preventScroll: true });'
        in ui
    )
    assert (
        'root.querySelector("[data-rakit-filter-rail-hide]")?.focus({ preventScroll: true });'
        in ui
    )


def test_bulk_selection_and_action_overflow_expose_meaningful_semantics() -> None:
    table = _read("templates", "resources", "_table.html")
    actions = _read("templates", "components", "actions.html")

    assert 'data-rakit-selected-count role="status" aria-live="polite"' in table
    assert 'aria-atomic="true">0 selected</span>' in table
    assert 'aria-label="Select all records on this page"' in table
    assert 'aria-label="More bulk actions"' in table

    assert 'data-rakit-action-group role="group" aria-label="{{ label }}"' in actions
    assert 'aria-label="More {{ label | lower }}"' in actions


def test_relationship_row_controls_include_record_context() -> None:
    row_actions = _read("templates", "relationships", "_row_actions.html")
    to_many = _read("templates", "relationships", "to_many.html")

    for template in (row_actions, to_many):
        assert (
            'aria-label="Remove {{ row.candidate.label }} from '
            '{{ panel.relationship.label }}"'
        ) in template
        assert (
            'aria-label="Undo removal of {{ row.candidate.label }} from '
            '{{ panel.relationship.label }}"'
        ) in template
        assert (
            'aria-label="Toggle removal of {{ row.candidate.label }} from '
            '{{ panel.relationship.label }}"'
        ) in template
        assert 'aria-label="Delete {{ row.candidate.label }}"' in template


def test_theme_menu_keeps_native_keyboard_menu_contract() -> None:
    template = _read("templates", "components", "theme_control.html")
    script = _read("static", "theme.js")

    assert 'aria-haspopup="menu"' in template
    assert 'role="menu"' in template
    assert 'role="menuitemradio"' in template
    assert 'aria-checked="false"' in template

    assert 'event.key === "ArrowDown"' in script
    assert 'event.key === "ArrowUp"' in script
    assert 'event.key === "Home" || event.key === "End"' in script
    assert 'event.key === "Escape"' in script
    assert "focus({ preventScroll: true })" in script
