"""Public Admin composition contract for custom pages."""

import pytest
from rakit_core.actions import (
    ActionDefinition,
    ActionScope,
    ActionSuccess,
    DomainActionExecutor,
)
from rakit_core.definitions import PageDefinition
from rakit_core.errors import RakitError
from rakit_web.admin import Admin


def _handler() -> DomainActionExecutor:
    return DomainActionExecutor(lambda _context: ActionSuccess())


def test_admin_register_page_composes_page_and_page_actions() -> None:
    admin = Admin(title="Operations", debug=True)
    page = PageDefinition(page_id="report", path="/reports", label="Report")
    action = ActionDefinition(
        action_id="refresh_report",
        label="Refresh",
        scope=ActionScope.PAGE,
        page_id="report",
        executor=_handler(),
    )

    admin.register_page(page, actions=(action,))
    compiled = admin.compile()

    assert compiled.pages == (page,)
    assert compiled.compiled_pages[0].definition is page
    assert compiled.compiled_pages[0].permission.permissions == ("admin.pages.report.view",)
    routes = {route.route_name: route for route in compiled.routes}
    assert routes["page:report"].path == "/reports"
    assert routes["page:report"].methods == ("GET",)
    assert routes["page:report:action:refresh_report"].path == "/reports/_actions/refresh_report"
    assert compiled.action_routes == (
        (routes["page:report:action:refresh_report"], compiled.compiled_actions[0]),
    )


def test_register_page_rejects_mismatched_action_before_builder_mutation() -> None:
    admin = Admin(title="Operations", debug=True)
    page = PageDefinition(page_id="report", path="/reports", label="Report")
    action = ActionDefinition(
        action_id="refresh",
        label="Refresh",
        scope=ActionScope.PAGE,
        page_id="other",
        executor=_handler(),
    )

    with pytest.raises(RakitError) as caught:
        admin.register_page(page, actions=(action,))

    assert caught.value.details["reason"] == "page_owner_mismatch"
    assert admin.builder.pages == ()
    assert admin.builder.actions == ()


def test_register_page_rejects_duplicate_action_before_builder_mutation() -> None:
    admin = Admin(title="Operations", debug=True)
    existing = ActionDefinition(
        action_id="refresh",
        label="Existing",
        scope=ActionScope.PAGE,
        page_id="existing",
        executor=_handler(),
    )
    admin.builder.add_page(PageDefinition(page_id="existing", path="/existing", label="Existing"))
    admin.builder.add_action(existing)
    page = PageDefinition(page_id="report", path="/reports", label="Report")
    duplicate = ActionDefinition(
        action_id="refresh",
        label="Duplicate",
        scope=ActionScope.PAGE,
        page_id="report",
        executor=_handler(),
    )

    with pytest.raises(RakitError) as caught:
        admin.register_page(page, actions=(duplicate,))

    assert caught.value.details["reason"] == "duplicate_action"
    assert {str(item.page_id) for item in admin.builder.pages} == {"existing"}
