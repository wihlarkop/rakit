import math
import re
from collections.abc import Mapping
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from uuid import UUID

from rakit_core.definitions import ResourceFieldPolicy
from rakit_core.errors import ErrorCode, RakitError
from rakit_core.fields import FieldDefinition
from rakit_core.generated_api import CompiledResourceApi, GeneratedCrudOperation
from rakit_core.generated_input import GeneratedInput, validate_generated_input
from rakit_core.generated_query import GeneratedFilterValue, build_generated_resource_query
from rakit_core.query import FilterOperator, ResourceQuery
from rakit_core.schema import SchemaAdapter
from starlette.datastructures import QueryParams

_FILTER_PATTERN = re.compile(r"^filter\[([^\]]+)\](?:\[([^\]]+)\])?$")
_SINGLETON_QUERY_PARAMS = frozenset({"page", "per_page", "sort", "search"})


def _transport_error(
    api: CompiledResourceApi,
    reason: str,
    *,
    message: str = "Generated REST request is invalid.",
    status_code: int = 400,
    details: Mapping[str, object] | None = None,
) -> RakitError:
    payload: dict[str, object] = {"resource_id": api.resource_id, "reason": reason}
    if details is not None:
        payload.update(details)
    return RakitError(
        code=ErrorCode.VALIDATION_FAILED,
        message=message,
        status_code=status_code,
        details=payload,
    )


def _parse_positive_int(api: CompiledResourceApi, name: str, raw: str | None, default: int) -> int:
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise _transport_error(api, "generated_api_invalid_pagination") from exc


def _filter_value(
    api: CompiledResourceApi,
    operator: FilterOperator,
    raw_value: str,
) -> object:
    if operator is FilterOperator.IN:
        values = tuple(part.strip() for part in raw_value.split(",") if part.strip())
        if not values:
            raise _transport_error(api, "generated_api_filter_value_invalid")
        return values
    if operator is FilterOperator.IS_NULL:
        normalized = raw_value.strip().lower()
        if normalized == "true":
            return True
        if normalized == "false":
            return False
        raise _transport_error(api, "generated_api_filter_value_invalid")
    return raw_value


def parse_generated_rest_query(
    api: CompiledResourceApi,
    field_policy: ResourceFieldPolicy,
    params: QueryParams,
) -> ResourceQuery:
    items = tuple(params.multi_items())
    raw_names = [name for name, _ in items]

    for name in _SINGLETON_QUERY_PARAMS:
        if raw_names.count(name) > 1:
            raise _transport_error(api, "generated_api_query_parameter_duplicated")

    filters: list[GeneratedFilterValue] = []
    seen_filter_keys: set[str] = set()
    for name, raw_value in items:
        if name in _SINGLETON_QUERY_PARAMS:
            continue
        match = _FILTER_PATTERN.fullmatch(name)
        if match is None:
            raise _transport_error(api, "generated_api_query_parameter_not_allowed")
        if name in seen_filter_keys:
            raise _transport_error(api, "generated_api_filter_duplicated")
        seen_filter_keys.add(name)
        filter_name, raw_operator = match.groups()
        try:
            operator = FilterOperator(raw_operator or FilterOperator.EQ.value)
        except ValueError as exc:
            raise _transport_error(api, "generated_api_filter_operator_not_allowed") from exc
        filters.append(
            GeneratedFilterValue(
                name=filter_name,
                operator=operator,
                value=_filter_value(api, operator, raw_value),
            )
        )

    search = params.get("search")
    if search is not None and not field_policy.search_fields:
        raise _transport_error(api, "generated_api_search_not_allowed")

    page = _parse_positive_int(api, "page", params.get("page"), 1)
    per_page = _parse_positive_int(api, "per_page", params.get("per_page"), 25)
    return build_generated_resource_query(
        api,
        field_policy,
        sort=params.get("sort"),
        page=page,
        per_page=per_page,
        filters=tuple(filters),
        search=search,
    )


def validate_generated_rest_payload(
    api: CompiledResourceApi,
    operation: GeneratedCrudOperation,
    payload: object,
    field_definitions: tuple[FieldDefinition, ...],
    *,
    schema_adapter: SchemaAdapter | None = None,
) -> GeneratedInput:
    if not isinstance(payload, Mapping) or not all(isinstance(key, str) for key in payload):
        raise _transport_error(api, "generated_api_json_object_required")
    values = {str(key): value for key, value in payload.items()}
    return validate_generated_input(
        api,
        operation,
        values,
        field_definitions,
        schema_adapter=schema_adapter,
    )


def _record_field(record: object, field_name: str) -> object:
    if isinstance(record, Mapping):
        if field_name not in record:
            raise KeyError(field_name)
        return record[field_name]
    if not hasattr(record, field_name):
        raise KeyError(field_name)
    return getattr(record, field_name)


def _json_safe(api: CompiledResourceApi, value: object) -> object:
    if value is None or isinstance(value, bool | int | str):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise _transport_error(
                api,
                "generated_api_output_not_serializable",
                status_code=500,
                message="Generated API output cannot be serialized safely.",
            )
        return value
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, datetime | date):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, Enum):
        return _json_safe(api, value.value)
    if isinstance(value, Mapping):
        if not all(isinstance(key, str) for key in value):
            raise _transport_error(
                api,
                "generated_api_output_not_serializable",
                status_code=500,
                message="Generated API output cannot be serialized safely.",
            )
        return {str(key): _json_safe(api, item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [_json_safe(api, item) for item in value]
    raise _transport_error(
        api,
        "generated_api_output_not_serializable",
        status_code=500,
        message="Generated API output cannot be serialized safely.",
    )


def serialize_generated_record(
    api: CompiledResourceApi,
    record: object,
    *,
    schema_adapter: SchemaAdapter | None = None,
) -> dict[str, object]:
    schema = api.definition.output_schema
    if schema is not None:
        if schema_adapter is None:
            raise RakitError(
                code=ErrorCode.CONFIG_INVALID,
                message="Generated API output schema requires a schema adapter.",
                status_code=500,
                details={
                    "resource_id": api.resource_id,
                    "reason": "generated_api_output_schema_adapter_missing",
                },
            )
        serialized = schema_adapter.serialize_output(schema, record)
        if not isinstance(serialized, Mapping) or not all(
            isinstance(key, str) for key in serialized
        ):
            raise RakitError(
                code=ErrorCode.CONFIG_INVALID,
                message="Generated API output schema must serialize to an object.",
                status_code=500,
                details={
                    "resource_id": api.resource_id,
                    "reason": "generated_api_output_schema_not_mapping",
                },
            )
        serialized_mapping = {str(key): value for key, value in serialized.items()}
        widened = set(serialized_mapping).difference(api.read_fields)
        if widened:
            raise RakitError(
                code=ErrorCode.CONFIG_INVALID_RESOURCE_POLICY,
                message="Generated API output schema widened the configured read fields.",
                status_code=500,
                details={
                    "resource_id": api.resource_id,
                    "reason": "generated_api_output_schema_widened_field_policy",
                    "fields": sorted(widened),
                },
            )
        safe = _json_safe(api, serialized_mapping)
        assert isinstance(safe, dict)
        return safe

    projected: dict[str, object] = {}
    try:
        for field_name in api.read_fields:
            projected[field_name] = _record_field(record, field_name)
    except KeyError as exc:
        raise RakitError(
            code=ErrorCode.INTERNAL_ERROR,
            message="Generated API record is missing a configured output field.",
            status_code=500,
            details={
                "resource_id": api.resource_id,
                "reason": "generated_api_output_field_missing",
                "field": str(exc.args[0]),
            },
        ) from exc
    safe = _json_safe(api, projected)
    assert isinstance(safe, dict)
    return safe


def generated_error_payload(error: RakitError, *, request_id: str) -> dict[str, object]:
    return {
        "error": error.to_public_dict(),
        "request_id": request_id,
    }


__all__ = [
    "generated_error_payload",
    "parse_generated_rest_query",
    "serialize_generated_record",
    "validate_generated_rest_payload",
]
