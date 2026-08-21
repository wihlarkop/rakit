from __future__ import annotations

from http import HTTPStatus
from importlib import metadata
from typing import cast

from rakit_core.errors import ErrorCode, RakitError
from rakit_core.integrations import integration_descriptor_from
from rakit_core.schema import SchemaAdapter

_SCHEMA_ADAPTER_ENTRY_POINT_GROUP = "rakit.schema_adapters"
_DEFAULT_SCHEMA_INTEGRATION_ID = "schema.pydantic"


def _installed_schema_adapter_entry_points() -> dict[str, metadata.EntryPoint]:
    selected = metadata.entry_points().select(group=_SCHEMA_ADAPTER_ENTRY_POINT_GROUP)
    installed: dict[str, metadata.EntryPoint] = {}
    for entry_point in selected:
        if entry_point.name in installed:
            raise RakitError(
                code=ErrorCode.CONFIG_INVALID,
                message="Duplicate schema adapter integration identifier.",
                status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
                details={
                    "reason": "schema_adapter_duplicate",
                    "integration_id": entry_point.name,
                },
            )
        installed[entry_point.name] = entry_point
    return installed


def installed_schema_adapter_ids() -> tuple[str, ...]:
    return tuple(sorted(_installed_schema_adapter_entry_points()))


def _load_schema_adapter(
    integration_id: str,
    *,
    installed: dict[str, metadata.EntryPoint],
) -> SchemaAdapter:
    entry_point = installed.get(integration_id)
    if entry_point is None:
        raise RakitError(
            code=ErrorCode.CONFIG_INVALID,
            message="Requested schema adapter integration is not installed.",
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            details={
                "reason": "schema_adapter_unavailable",
                "integration_id": integration_id,
                "available": tuple(sorted(installed)),
            },
        )

    loaded = entry_point.load()
    adapter = loaded() if isinstance(loaded, type) else loaded
    provider = getattr(adapter, "provider", None)
    if provider is None:
        raise RakitError(
            code=ErrorCode.CONFIG_INVALID,
            message="Schema adapter entry point does not expose capability metadata.",
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            details={
                "reason": "schema_adapter_invalid",
                "integration_id": integration_id,
            },
        )
    descriptor = integration_descriptor_from(adapter)
    if descriptor is None or descriptor.integration_id != integration_id:
        raise RakitError(
            code=ErrorCode.CONFIG_INVALID,
            message=(
                "Schema adapter entry point integration metadata does not match its identifier."
            ),
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            details={
                "reason": "schema_adapter_metadata_mismatch",
                "integration_id": integration_id,
            },
        )
    return cast(SchemaAdapter, adapter)


def resolve_schema_adapter(
    schema_adapter: SchemaAdapter | None,
    *,
    schema_integration_id: str | None,
) -> SchemaAdapter:
    if schema_adapter is not None:
        if schema_integration_id is not None:
            descriptor = integration_descriptor_from(schema_adapter)
            if descriptor is None or descriptor.integration_id != schema_integration_id:
                raise RakitError(
                    code=ErrorCode.CONFIG_INVALID,
                    message="Explicit schema adapter conflicts with schema_integration_id.",
                    status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
                    details={
                        "reason": "schema_adapter_selection_conflict",
                        "integration_id": schema_integration_id,
                    },
                )
        return schema_adapter

    installed = _installed_schema_adapter_entry_points()
    integration_id = schema_integration_id or _DEFAULT_SCHEMA_INTEGRATION_ID
    return _load_schema_adapter(integration_id, installed=installed)


__all__ = ["installed_schema_adapter_ids", "resolve_schema_adapter"]
