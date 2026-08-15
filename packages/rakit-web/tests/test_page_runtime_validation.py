"""Task 6 runtime-only Page capability validation."""

import pytest
from rakit_core.compiler import ApplicationBuilder, compile_application
from rakit_core.definitions import PageDefinition
from rakit_core.errors import RakitError
from rakit_web.page_admin import validate_page_runtime


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
