from importlib.resources import files


def _read(*parts: str) -> str:
    return files("rakit_web").joinpath(*parts).read_text()


def test_shared_responsive_primitives_bound_buttons_dialogs_and_popovers() -> None:
    source = _read("assets", "rakit.css")
    generated = _read("static", "rakit.css")

    assert "min-h-9 max-w-full" in source
    assert "whitespace-normal" in source
    assert "w-[min(32rem,calc(100%_-_2rem))]" in source
    assert "max-height: calc(100dvh - 2rem);" in source
    assert "max-w-[calc(100vw_-_2rem)]" in source
    assert "[overflow-wrap:anywhere]" in source

    assert "100dvh" in generated
    assert "overflow-wrap:anywhere" in generated


def test_mobile_navigation_and_filter_drawer_are_viewport_bounded() -> None:
    mobile_navigation = _read("templates", "components", "admin_mobile_navigation.html")
    resource_table = _read("templates", "resources", "_table.html")

    assert "w-[min(20rem,calc(100vw_-_3rem))]" in mobile_navigation
    assert "calc(100%-3rem)" not in mobile_navigation

    assert "w-[min(24rem,calc(100vw_-_1rem))]" in resource_table
    assert "calc(100vw-1rem)" not in resource_table
    assert '<div class="overflow-x-auto">' in resource_table
    assert 'class="rakit-pagination max-w-full"' in resource_table


def test_resource_heading_actions_and_long_values_stay_narrow_safe() -> None:
    resource_list = _read("templates", "resources", "list.html")
    resource_detail = _read("templates", "resources", "detail.html")
    resource_table = _read("templates", "resources", "_table.html")

    assert "gap-4 md:flex-row md:items-start" in resource_list
    assert 'w-full max-w-full flex-wrap items-start gap-2 md:w-auto' in resource_list
    assert "[overflow-wrap:anywhere]" in resource_list

    assert "gap-4 md:flex-row md:items-start" in resource_detail
    assert 'w-full max-w-full flex-wrap items-start gap-2 md:w-auto' in resource_detail
    assert resource_detail.count("[overflow-wrap:anywhere]") >= 3

    assert 'class="self-start text-sm tabular-nums text-rakit-text-muted lg:self-auto"' in resource_table
    assert 'text-rakit-text [overflow-wrap:anywhere]' in resource_table


def test_forms_actions_relationships_and_pages_wrap_long_content() -> None:
    form = _read("templates", "forms", "form.html")
    actions = _read("templates", "components", "actions.html")
    action_confirm = _read("templates", "actions", "_confirm.html")
    relationship_panel = _read("templates", "relationships", "panel.html")
    relationship_many = _read("templates", "relationships", "to_many.html")
    relationship_inline = _read("templates", "relationships", "inline_rows.html")
    page = _read("templates", "pages", "page.html")

    assert "field.file.current.name" in form
    assert form.count("[overflow-wrap:anywhere]") >= 2

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


def test_auth_system_header_reserves_space_for_theme_control() -> None:
    base = _read("templates", "base.html")

    assert "min-w-0 flex-1 truncate" in base
    assert "w-32 shrink-0 sm:w-36" in base
