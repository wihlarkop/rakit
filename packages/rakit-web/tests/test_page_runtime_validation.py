"""Task 6 runtime-only Page capability validation."""

import pytest
from rakit_core.compiler import ApplicationBuilder, compile_application
from rakit_core.definitions import PageDefinition
from rakit_core.errors import RakitError
from rakit_core.permissions import PermissionRequirement
from rakit_web.page_admin import page_requirement_map, validate_page_runtime
from rakit_web.security.authentication import build_requirement_resolver


def test_parameterized_page_keeps_compiler_contract_but_runtime_fails_closed() -> None:
    builder = ApplicationBuilder(admin_id="ops")
    page = PageDefinition(
        page_id="dynamic",
        path="/reports/{report_id}",
        label="Dynamic report",
    )
    builder.add_page(page)
    compiled = compile_application(builder)
    assert compiled.pages == (page,)

    with pytest.raises(RakitError) as caught:
        validate_page_runtime(
            compiled,
            auth_enabled=True,
            idempotency_store=None,
            uow_factory_registered=False,
            debug=True,
        )

    assert caught.value.details == {
        "page_id": "dynamic",
        "path": "/reports/{report_id}",
        "reason": "page_path_parameters_not_supported",
    }


def test_custom_compiled_page_permission_is_the_exact_middleware_requirement() -> None:
    permission = PermissionRequirement.all_of("ops.reports.special")
    builder = ApplicationBuilder(admin_id="ops")
    builder.add_page(
        PageDefinition(
            page_id="report",
            path="/reports",
            label="Report",
            permission=permission,
        )
    )
    compiled = compile_application(builder)
    resolve = build_requirement_resolver(
        admin_id="ops",
        resource_paths={},
        action_requirements=page_requirement_map(compiled),
    )

    assert resolve("/reports") == permission
