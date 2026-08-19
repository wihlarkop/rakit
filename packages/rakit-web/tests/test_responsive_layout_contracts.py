from importlib.resources import files


def _read(*path: str) -> str:
    return files("rakit_web").joinpath(*path).read_text(encoding="utf-8")


def test_shell_navigation_and_dialogs_stay_viewport_bounded() -> None:
    desktop = _read("templates", "components", "admin_navigation.html")
    mobile = _read("templates", "components", "admin_mobile_navigation.html")
    dialog = _read("templates", "components", "dialog.html")
    theme = _read("templates", "components", "theme_control.html")

    assert "max-w-[calc(100vw-2rem)]" in desktop
    assert "max-w-[calc(100vw-2rem)]" in mobile
    assert "max-w-[calc(100vw-2rem)]" in dialog
    assert "max-w-[calc(100vw-2rem)]" in theme


def test_dashboard_and_resource_headers_adapt_without_page_overflow() -> None:
    dashboard = _read("templates", "dashboard.html")
    resource_list = _read("templates", "resources", "list.html")
    resource_detail = _read("templates", "resources", "detail.html")
    resource_table = _read("templates", "resources", "_table.html")

    assert "flex flex-col gap-4 md:flex-row" in dashboard
    assert dashboard.count("min-w-0") >= 2

    assert "flex flex-col gap-4 md:flex-row md:items-start" in resource_list
    assert "w-full max-w-full flex-wrap items-start gap-2 md:w-auto" in resource_list
    assert resource_list.count("[overflow-wrap:anywhere]") >= 2

    assert "gap-4 md:flex-row md:items-start" in resource_detail
    assert "w-full max-w-full flex-wrap items-start gap-2 md:w-auto" in resource_detail
    assert resource_detail.count("[overflow-wrap:anywhere]") >= 3

    expected_total_class = (
        'class="self-start text-sm tabular-nums text-rakit-text-muted lg:self-auto"'
    )
    assert expected_total_class in resource_table
    assert "text-rakit-text [overflow-wrap:anywhere]" in resource_table


def test_forms_actions_relationships_and_pages_wrap_long_content() -> None:
    form = _read("templates", "forms", "form.html")
    field_control = _read("templates", "forms", "_field_control.html")
    actions = _read("templates", "components", "actions.html")
    action_confirm = _read("templates", "actions", "_confirm.html")
    relationship_panel = _read("templates", "relationships", "panel.html")
    relationship_many = _read("templates", "relationships", "to_many.html")
    relationship_inline = _read("templates", "relationships", "inline_rows.html")
    page = _read("templates", "pages", "page.html")

    assert "field.file.current.name" in field_control
    assert (
        form.count("[overflow-wrap:anywhere]") + field_control.count("[overflow-wrap:anywhere]")
        >= 2
    )

    assert "inline-flex max-w-full flex-col" in actions
    assert "max-w-full text-xs" in actions
    assert "flex max-w-full flex-wrap" in actions
    assert "[overflow-wrap:anywhere]" in actions

    assert "flex flex-col-reverse gap-2" in action_confirm
    assert "[overflow-wrap:anywhere]" in action_confirm

    assert 'class="min-w-0"' in relationship_panel
    assert "[overflow-wrap:anywhere]" in relationship_panel
    assert relationship_many.count("[overflow-wrap:anywhere]") >= 2
    assert "justify-start gap-2 sm:justify-end" in relationship_many
    assert "max-w-64" in relationship_inline
    assert "[overflow-wrap:anywhere]" in relationship_inline

    assert "flex flex-col items-start gap-4" in page
    assert page.count("[overflow-wrap:anywhere]") >= 3


def test_narrow_viewports_keep_long_content_inside_intentional_scroll_regions() -> None:
    resource_table = _read("templates", "resources", "_table.html")
    relationship_many = _read("templates", "relationships", "to_many.html")
    dashboard_table = _read("templates", "dashboard", "widget_table.html")

    for template in (resource_table, relationship_many, dashboard_table):
        assert "overflow-x-auto" in template

    assert 'table class="min-w-full' in resource_table
    assert 'table class="min-w-full' in relationship_many
    assert 'table class="min-w-full' in dashboard_table
