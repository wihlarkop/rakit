import pytest
from rakit_core.config import RakitConfig, SecretValue
from rakit_core.errors import RakitError
from rakit_web.security.validation import validate_production_config


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
