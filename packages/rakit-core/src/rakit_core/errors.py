from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


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
    DI_CIRCULAR_DEPENDENCY = "di.circular_dependency"
    DI_CAPTIVE_DEPENDENCY = "di.captive_dependency"
    DI_DUPLICATE_REGISTRATION = "di.duplicate_registration"
    DI_REGISTRY_FROZEN = "di.registry_frozen"
    DI_INVALID_VALUE_SCOPE = "di.invalid_value_scope"
    EVENTS_QUEUE_DEPTH_EXCEEDED = "events.queue_depth_exceeded"
    EVENTS_CAUSATION_DEPTH_EXCEEDED = "events.causation_depth_exceeded"
    EVENTS_DRAIN_BUDGET_EXCEEDED = "events.drain_budget_exceeded"
    EVENTS_NESTED_PUBLISH_PRE_NOT_ALLOWED = "events.nested_publish_pre_not_allowed"
    EVENTS_ENQUEUE_PRE_WITHOUT_ACTIVE_DRAIN = "events.enqueue_pre_without_active_drain"
    CONFIG_MISSING_PLUGIN_DEPENDENCY = "config.missing_plugin_dependency"
    CONFIG_PLUGIN_CONFLICT = "config.plugin_conflict"
    CONFIG_RESERVED_PATH = "config.reserved_path"
    CONFIG_ROUTE_NAME_COLLISION = "config.route_name_collision"
    CONFIG_ROUTE_COLLISION = "config.route_collision"
    CONFIG_DUPLICATE_PLUGIN = "config.duplicate_plugin"
    CONFIG_ALREADY_COMPILED = "config.already_compiled"
    CONFIG_COMPILE_DURING_PLUGIN_INSTALL = "config.compile_during_plugin_install"
    CONFIG_PLUGIN_FROZE_REGISTRY = "config.plugin_froze_registry"
    CONFIG_DUPLICATE_ADAPTER = "config.duplicate_adapter"
    CONFIG_DUPLICATE_RESOURCE = "config.duplicate_resource"
    CONFIG_ADAPTER_NOT_FOUND = "config.adapter_not_found"
    CONFIG_ADAPTER_AMBIGUOUS = "config.adapter_ambiguous"
    CONFIG_RESOURCE_MISSING_DATA_SOURCE = "config.resource_missing_data_source"
    CONFIG_INVALID_RESOURCE_POLICY = "config.invalid_resource_policy"
    CONFIG_INVALID_DATASOURCE = "config.invalid_datasource"
    CONFIG_UNSUPPORTED_IDENTITY = "config.unsupported_identity"


class ErrorDetail(BaseModel):
    model_config = ConfigDict(frozen=True)

    location: tuple[str | int, ...] = ()
    code: str
    message: str
    context: dict[str, Any] = Field(default_factory=dict)


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
