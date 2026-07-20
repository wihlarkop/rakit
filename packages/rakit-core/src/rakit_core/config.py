from typing import Annotated, Self

from pydantic import BaseModel, ConfigDict, Field, SecretStr, model_validator

MachineId = Annotated[str, Field(pattern=r"^[a-z][a-z0-9_]*$")]


class SecretValue(SecretStr):
    pass


class SecurityConfig(BaseModel):
    model_config = ConfigDict(frozen=True)

    secret_key: SecretValue | None = None
    allowed_hosts: tuple[str, ...] = ("localhost", "127.0.0.1", "[::1]")
    content_security_policy_enabled: bool = True


class LifecycleConfig(BaseModel):
    model_config = ConfigDict(frozen=True)

    graceful_shutdown_timeout_seconds: float = Field(default=30.0, gt=0)


class RakitConfig(BaseModel):
    model_config = ConfigDict(frozen=True)

    admin_id: MachineId = "admin"
    title: str = Field(min_length=1)
    debug: bool = False
    security: SecurityConfig = SecurityConfig()
    lifecycle: LifecycleConfig = LifecycleConfig()

    @model_validator(mode="after")
    def require_production_secret(self) -> Self:
        if not self.debug and self.security.secret_key is None:
            raise ValueError("A persistent security.secret_key is required when debug=False")
        return self
