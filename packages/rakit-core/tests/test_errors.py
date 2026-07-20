from rakit_core.errors import ErrorCode, ErrorDetail, RakitError


def test_error_detail_context_defaults_are_independent_per_instance() -> None:
    first = ErrorDetail(code="a", message="a")
    second = ErrorDetail(code="b", message="b")

    assert first.context is not second.context
    assert first.context == {}
    assert second.context == {}


def test_public_error_excludes_internal_cause() -> None:
    error = RakitError(
        code=ErrorCode.CONFIG_INVALID,
        message="Configuration is invalid.",
        status_code=500,
        details={"field": "security.secret_key"},
        cause=RuntimeError("secret=abc"),
    )

    assert error.to_public_dict() == {
        "code": "config.invalid",
        "message": "Configuration is invalid.",
        "details": {"field": "security.secret_key"},
    }
