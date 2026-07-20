from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict


class ErrorCode(StrEnum):
    CONFIG_INVALID = "config.invalid"
    CONFIG_VERSION_MISMATCH = "config.package_version_mismatch"
    VALIDATION_FAILED = "validation.failed"
    AUTH_UNAUTHENTICATED = "auth.unauthenticated"
    AUTH_FORBIDDEN = "auth.forbidden"
    RESOURCE_NOT_FOUND = "resource.not_found"
    RESOURCE_CONFLICT = "resource.conflict"
    DATASOURCE_FAILURE = "datasource.failure"
    OPERATION_TIMEOUT = "operation.timeout"
    INTERNAL_ERROR = "internal.error"


class ErrorDetail(BaseModel):
    model_config = ConfigDict(frozen=True)

    location: tuple[str | int, ...] = ()
    code: str
    message: str
    context: dict[str, Any] = {}


class RakitError(Exception):
    def __init__(
        self,
        *,
        code: ErrorCode | str,
        message: str,
        status_code: int,
        details: dict[str, Any] | None = None,
        cause: BaseException | None = None,
    ) -> None:
        super().__init__(message)
        self.code = str(code)
        self.message = message
        self.status_code = status_code
        self.details = details or {}
        self.__cause__ = cause

    def to_public_dict(self) -> dict[str, Any]:
        payload = {"code": self.code, "message": self.message}
        if self.details:
            payload["details"] = self.details
        return payload


class RakitWarning(Warning):
    pass


class RakitDeprecationWarning(RakitWarning):
    pass


class RakitConfigurationWarning(RakitWarning):
    pass


class RakitPerformanceWarning(RakitWarning):
    pass


class RakitSecurityWarning(RakitWarning):
    pass
