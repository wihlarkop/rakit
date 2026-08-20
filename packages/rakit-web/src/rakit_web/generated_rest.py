import math
import re
from collections.abc import Mapping
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from http import HTTPStatus
from typing import cast
from uuid import UUID

from rakit_core.definitions import ResourceFieldPolicy
from rakit_core.errors import ErrorCode, RakitError
from rakit_core.fields import FieldDefinition
from rakit_core.generated_api import CompiledResourceApi, GeneratedCrudOperation
from rakit_core.generated_input import GeneratedInput, validate_generated_input
from rakit_core.generated_query import GeneratedFilterValue, build_generated_resource_query
from rakit_core.pagination import (
    CursorPagination,
    LimitOffsetPagination,
    PagePagination,
    PaginationStrategy,
)
from rakit_core.query import FilterOperator, ResourceQuery
from rakit_core.schema import SchemaAdapter
from starlette.datastructures import QueryParams

_FILTER_PATTERN = re.compile(r"^filter\[([^\]]+)\](?:\[([^\]]+)\])?$")
_COMMON_QUERY_PARAMS = frozenset({"sort", "search"})
_PAGINATION_QUERY_PARAMS = frozenset({"page", "per_page", "offset", "limit", "cursor"})


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


def _parse_int(
    api: CompiledResourceApi,
    name: str,
    raw: str | None,
    default: int,
    *,
    minimum: int,
) -> int:
    if raw is None:
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise _transport_error(api, "generated_api_invalid_pagination") from exc
    if value < minimum:
        raise _transport_error(api, "generated_api_invalid_pagination")
    return value


def _query_params_for_strategy(api: CompiledResourceApi) -> frozenset[str]:
    strategy = api.pagination.strategy
    if strategy is PaginationStrategy.PAGE:
        return _COMMON_QUERY_PARAMS | {"page", "per_page"}
    if strategy is PaginationStrategy.LIMIT_OFFSET:
        return _COMMON_QUERY_PARAMS | {"offset", "limit"}
    return _COMMON_QUERY_PARAMS | {"cursor", "limit"}


def _parse_pagination(api: CompiledResourceApi, params: QueryParams):
    policy = api.pagination
    if policy.strategy is PaginationStrategy.PAGE:
        page = _parse_int(api, "page", params.get("page"), 1, minimum=1)
        size = _parse_int(
            api,
            "per_page",
            params.get("per_page"),
            policy.size.default,
            minimum=1,
        )
        if not policy.size.accepts(size):
            raise _transport_error(api, "generated_api_invalid_pagination")
        return PagePagination(page=page, per_page=size)
    if policy.strategy is PaginationStrategy.LIMIT_OFFSET:
        offset = _parse_int(api, "offset", params.get("offset"), 0, minimum=0)
        size = _parse_int(
            api,
            "limit",
            params.get("limit"),
            policy.size.default,
            minimum=1,
        )
        if not policy.size.accepts(size):
            raise _transport_error(api, "generated_api_invalid_pagination")
        return LimitOffsetPagination(offset=offset, limit=size)
    size = _parse_int(
        api,
        "limit",
        params.get("limit"),
        policy.size.default,
        minimum=1,
    )
    if not policy.size.accepts(size):
        raise _transport_error(api, "generated_api_invalid_pagination")
    cursor = params.get("cursor")
    if cursor == "":
        raise _transport_error(api, "generated_api_invalid_pagination")
    return CursorPagination(cursor=cursor, limit=size)


def parse_generated_rest_query(
    api: CompiledResourceApi,
    field_policy: ResourceFieldPolicy,
    params: QueryParams,
) -> ResourceQuery:
    items = tuple(params.multi_items())
    raw_names = [name for name, _ in items]
    allowed_query_params = _query_params_for_strategy(api)

    for name in raw_names:
        if name in _PAGINATION_QUERY_PARAMS and name not in allowed_query_params:
            raise _transport_error(api, "generated_api_query_parameter_not_allowed")
    for name in allowed_query_params:
        if raw_names.count(name) > 1:
            raise _transport_error(api, "generated_api_query_parameter_duplicated")

    filters: list[GeneratedFilterValue] = []
    seen_filter_keys: set[str] = set()
    for name, raw_value in items:
        if name in allowed_query_params:
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
                value=raw_value,
            )
        )

    search = params.get("search")
    if search is not None and not field_policy.search_fields:
        raise _transport_error(api, "generated_api_search_not_allowed")

    return build_generated_resource_query(
        api,
        field_policy,
        sort=params.get("sort"),
        pagination=_parse_pagination(api, params),
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
        record_mapping = cast(Mapping[str, object], record)
        if field_name not in record_mapping:
            raise KeyError(field_name)
        return record_mapping[field_name]
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
                status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
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
                status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
                message="Generated API output cannot be serialized safely.",
            )
        return {str(key): _json_safe(api, item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [_json_safe(api, item) for item in value]
    raise _transport_error(
        api,
        "generated_api_output_not_serializable",
        status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
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
                status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
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
                status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
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
                status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
                details={
                    "resource_id": api.resource_id,
                    "reason": "generated_api_output_schema_widened_field_policy",
                    "fields": sorted(widened),
                },
            )
        return {key: _json_safe(api, value) for key, value in serialized_mapping.items()}

    projected: dict[str, object] = {}
    try:
        for field_name in api.read_fields:
            projected[field_name] = _record_field(record, field_name)
    except KeyError as exc:
        raise RakitError(
            code=ErrorCode.INTERNAL_ERROR,
            message="Generated API record is missing a configured output field.",
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            details={
                "resource_id": api.resource_id,
                "reason": "generated_api_output_field_missing",
                "field": str(exc.args[0]),
            },
        ) from exc
    return {key: _json_safe(api, value) for key, value in projected.items()}


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
