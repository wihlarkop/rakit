import pytest
from pydantic import ValidationError
from rakit_core.config import RakitConfig, SecretValue


def test_config_is_frozen_and_secret_is_redacted() -> None:
    config = RakitConfig(
        admin_id="operations",
        title="Operations",
        debug=False,
        security={"secret_key": SecretValue("x" * 32)},
    )
    assert "x" * 32 not in repr(config)
    with pytest.raises(ValidationError):
        config.title = "Changed"  # type: ignore


def test_production_requires_secret() -> None:
    with pytest.raises(ValidationError):
        RakitConfig(admin_id="operations", title="Operations", debug=False)
