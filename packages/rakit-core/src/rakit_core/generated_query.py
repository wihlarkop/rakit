from dataclasses import dataclass

from .definitions import ResourceFieldPolicy
from .errors import ErrorCode, RakitError
from .generated_api import CompiledResourceApi
from .query import CountPolicy, Filter, FilterOperator, ResourceQuery


@dataclass(frozen=True, slots=True)
class GeneratedFilterValue:
    name: str
    operator: FilterOperator
    value: object


def _query_error(api: CompiledResourceApi, reason: str) -> RakitError:
    return RakitError(
        code=ErrorCode.VALIDATION_FAILED,
        message="Generated API query is not allowed.",
        status_code=400,
        details={"resource_id": api.resource_id, "reason": reason},
    )


def build_generated_resource_query(
    api: CompiledResourceApi,
    field_policy: ResourceFieldPolicy,
    *,
    sort: str | None = None,
    page: int = 1,
    per_page: int = 25,
    filters: tuple[GeneratedFilterValue, ...] = (),
    search: str | None = None,
    count_policy: CountPolicy = CountPolicy.EXACT,
) -> ResourceQuery:
    definitions = {definition.name: definition for definition in api.filters}
    resolved_filters: list[Filter] = []
    for submitted in filters:
        definition = definitions.get(submitted.name)
        if definition is None:
            raise _query_error(api, "generated_api_filter_not_allowed")
        if submitted.operator not in definition.operators:
            raise _query_error(api, "generated_api_filter_operator_not_allowed")
        resolved_filters.append(
            Filter(
                field=definition.field,
                operator=submitted.operator,
                value=submitted.value,
            )
        )

    try:
        return ResourceQuery.from_params(
            sort=sort,
            page=page,
            per_page=per_page,
            allowed_sort_fields=field_policy.sort_fields,
            identity_fields=api.identity_fields,
            filters=tuple(resolved_filters),
            search=search,
            count_policy=count_policy,
        )
    except (TypeError, ValueError) as exc:
        raise _query_error(api, "generated_api_query_not_allowed") from exc


__all__ = ["GeneratedFilterValue", "build_generated_resource_query"]
