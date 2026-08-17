from importlib.resources import files

TEMPLATES = files("rakit_web").joinpath("templates", "dashboard")


def _template_source(name: str) -> str:
    return TEMPLATES.joinpath(name).read_text(encoding="utf-8")


def test_dashboard_page_uses_semantic_operational_hierarchy() -> None:
    source = _template_source("index.html")

    assert source.count("<h1") == 1
    assert 'id="rakit-dashboard-launchers-title"' in source
    assert ">Quick access</h2>" in source
    assert 'id="rakit-dashboard-widgets-title"' in source
    assert ">Overview</h2>" in source
    assert "Nothing to show yet" in source
    assert 'rakit_icon("chevron-right"' in source
    assert "text-rakit-text" in source
    assert "text-rakit-text-muted" in source
    assert "border-rakit-border" in source
    assert "bg-rakit-surface" in source

    for legacy_role in (
        "text-slate-",
        "bg-slate-",
        "border-slate-",
        "text-blue-",
        "outline-blue-",
    ):
        assert legacy_role not in source


def test_dashboard_widget_uses_shared_primitives_and_preserves_htmx_contract() -> None:
    source = _template_source("_widget.html")

    assert 'class="rakit-panel md:col-span-12' in source
    assert 'class="rakit-panel-header"' in source
    assert 'class="rakit-panel-body"' in source
    assert 'class="rakit-alert rakit-alert-danger" role="alert"' in source
    assert 'role="status"' in source
    assert 'aria-live="polite"' in source
    assert 'aria-busy="true"' in source
    assert 'hx-trigger="load"' in source
    assert 'hx-swap="outerHTML"' in source
    assert 'hx-disabled-elt="this"' in source
    assert 'hx-indicator="#rakit-dashboard-widget-' in source
    assert 'aria-label="Refresh {{ result.label }}"' in source
    assert ">Refreshing…</span>" in source
    assert "xl:col-span-3" in source
    assert "xl:col-span-6" in source
    assert "xl:col-span-9" in source
    assert "xl:col-span-12" in source

    for legacy_role in (
        "text-slate-",
        "bg-slate-",
        "border-slate-",
        "text-blue-",
        "bg-red-",
        "text-red-",
        "border-red-",
    ):
        assert legacy_role not in source


def test_widget_result_shapes_remain_definition_driven() -> None:
    source = _template_source("_widget.html")

    for result_branch in (
        "result.message is defined",
        "result.template is defined",
        "result.value is defined",
        "result.text is defined",
        "result.columns is defined",
        "result.items is defined",
    ):
        assert result_branch in source

    assert "result.empty_message" in source
    assert "widget.definition.layout.size.value == 'small'" in source
    assert "widget.definition.layout.size.value == 'medium'" in source
    assert "widget.definition.layout.size.value == 'large'" in source
