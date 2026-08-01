from types import SimpleNamespace

import pytest
from rakit_core.config import RakitConfig, SecretValue
from rakit_core.errors import RakitError
from rakit_web.security import validation as validation_module
from rakit_web.security.rate_limit import LoginRateLimiter
from rakit_web.security.validation import (
    validate_production_config,
    validate_rate_limiter_for_production,
)


def _validate_session_store_for_production(
    store: object, *, debug: bool, auth_enabled: bool
) -> None:
    assert hasattr(validation_module, "validate_session_store_for_production")
    validation_module.validate_session_store_for_production(
        store, debug=debug, auth_enabled=auth_enabled
    )


def _config(**security_overrides: object) -> RakitConfig:
    return RakitConfig(
        title="Operations",
        debug=False,
        security={"secret_key": SecretValue("x" * 32), **security_overrides},
    )


def test_debug_config_is_never_validated() -> None:
    config = RakitConfig(title="Operations", debug=True)
    validate_production_config(config)


def test_valid_production_config_passes() -> None:
    validate_production_config(_config())


def test_wildcard_allowed_host_is_rejected() -> None:
    with pytest.raises(RakitError) as exc_info:
        validate_production_config(_config(allowed_hosts=("*",)))
    assert exc_info.value.details["reason"] == "wildcard_allowed_host"


def test_disabled_content_security_policy_is_rejected() -> None:
    with pytest.raises(RakitError) as exc_info:
        validate_production_config(_config(content_security_policy_enabled=False))
    assert exc_info.value.details["reason"] == "content_security_policy_disabled"


def test_overbroad_trusted_proxy_is_rejected() -> None:
    with pytest.raises(RakitError) as exc_info:
        validate_production_config(_config(trusted_proxies=("0.0.0.0/0",)))
    assert exc_info.value.details["reason"] == "overbroad_trusted_proxy"


def test_narrow_trusted_proxy_is_accepted() -> None:
    validate_production_config(_config(trusted_proxies=("10.0.0.0/24",)))


def test_short_secret_is_rejected() -> None:
    config = RakitConfig(
        title="Operations", debug=False, security={"secret_key": SecretValue("x" * 31)}
    )
    with pytest.raises(RakitError) as exc_info:
        validate_production_config(config)
    assert exc_info.value.details["reason"] == "weak_secret_key"


def test_exactly_minimum_length_secret_is_accepted() -> None:
    config = RakitConfig(
        title="Operations", debug=False, security={"secret_key": SecretValue("x" * 32)}
    )
    validate_production_config(config)


def test_debug_mode_never_validates_secret_length() -> None:
    config = RakitConfig(title="Operations", debug=True, security={"secret_key": SecretValue("x")})
    validate_production_config(config)


# --- validate_rate_limiter_for_production -------------------------------


def test_development_limiter_is_rejected_in_production_with_auth_enabled() -> None:
    with pytest.raises(RakitError) as exc_info:
        validate_rate_limiter_for_production(LoginRateLimiter(), debug=False, auth_enabled=True)
    assert exc_info.value.details["reason"] == "development_only_rate_limiter"


def test_development_limiter_is_accepted_in_debug_mode() -> None:
    validate_rate_limiter_for_production(LoginRateLimiter(), debug=True, auth_enabled=True)


def test_development_limiter_is_accepted_when_auth_is_not_enabled() -> None:
    validate_rate_limiter_for_production(LoginRateLimiter(), debug=False, auth_enabled=False)


def test_production_safe_limiter_is_accepted_in_production_with_auth_enabled() -> None:
    class _SharedLimiter:
        production_safe = True

        def check(self, *, admin_id: str, identifier: str, client_ip: str) -> bool:
            return True

    validate_rate_limiter_for_production(_SharedLimiter(), debug=False, auth_enabled=True)


def test_limiter_missing_production_safe_attribute_is_rejected() -> None:
    class _UndeclaredLimiter:
        def check(self, *, admin_id: str, identifier: str, client_ip: str) -> bool:
            return True

    with pytest.raises(RakitError) as exc_info:
        validate_rate_limiter_for_production(_UndeclaredLimiter(), debug=False, auth_enabled=True)
    assert exc_info.value.details["reason"] == "development_only_rate_limiter"


class _DevelopmentSessionStore:
    production_safe = False

    async def create(self, principal):
        raise NotImplementedError

    async def resolve(self, raw_token: str):
        return None

    async def rotate(self, session_id: str):
        raise NotImplementedError

    async def revoke(self, session_id: str) -> None:
        return None


def test_development_session_store_is_rejected_for_production_multi_worker_use() -> None:
    first_worker_store = _DevelopmentSessionStore()
    second_worker_store = _DevelopmentSessionStore()
    assert first_worker_store is not second_worker_store
    with pytest.raises(RakitError) as exc_info:
        _validate_session_store_for_production(first_worker_store, debug=False, auth_enabled=True)
    assert exc_info.value.details["reason"] == "development_only_session_store"


@pytest.mark.parametrize("declaration", ["yes", 1, object()])
def test_session_store_requires_literal_true_production_declaration(declaration: object) -> None:
    store = SimpleNamespace(production_safe=declaration)
    with pytest.raises(RakitError) as exc_info:
        _validate_session_store_for_production(store, debug=False, auth_enabled=True)
    assert exc_info.value.details["reason"] == "development_only_session_store"


@pytest.mark.parametrize(
    ("method", "reason"),
    [
        ("create", "session_store_create_not_callable"),
        ("resolve", "session_store_resolve_not_callable"),
        ("rotate", "session_store_rotate_not_callable"),
        ("revoke", "session_store_revoke_not_callable"),
    ],
)
def test_session_store_requires_each_documented_callable(method: str, reason: str) -> None:
    store = _DevelopmentSessionStore()
    store.production_safe = True
    setattr(store, method, None)
    with pytest.raises(RakitError) as exc_info:
        _validate_session_store_for_production(store, debug=False, auth_enabled=True)
    assert exc_info.value.details["reason"] == reason


def test_session_store_rejects_incompatible_method_signature() -> None:
    class _WrongSignatureStore:
        production_safe = True

        async def create(self) -> None:
            return None

        async def resolve(self, raw_token: str):
            return None

        async def rotate(self, session_id: str):
            raise NotImplementedError

        async def revoke(self, session_id: str) -> None:
            return None

    with pytest.raises(RakitError) as exc_info:
        _validate_session_store_for_production(
            _WrongSignatureStore(), debug=False, auth_enabled=True
        )
    assert exc_info.value.details["reason"] == "session_store_create_not_callable"


def test_debug_and_no_auth_skip_session_store_production_validation() -> None:
    _validate_session_store_for_production(
        _DevelopmentSessionStore(), debug=True, auth_enabled=True
    )
    _validate_session_store_for_production(
        _DevelopmentSessionStore(), debug=False, auth_enabled=False
    )
