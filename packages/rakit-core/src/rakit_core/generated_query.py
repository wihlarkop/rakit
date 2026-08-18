from dataclasses import dataclass

from .definitions import ResourceFieldPolicy
from .errors import ErrorCode, RakitError
from .filters import Filter, FilterOperator, FilterSelection, resolve_filter_selection
from .generated_api import CompiledResourceApi
from .pagination import PagePagination, ResourcePagination
from .query import CountPolicy, ResourceQuery


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
    pagination: ResourcePagination | None = None,
    filters: tuple[GeneratedFilterValue, ...] = (),
    search: str | None = None,
    count_policy: CountPolicy = CountPolicy.EXACT,
) -> ResourceQuery:
    definitions = {definition.name: definition for definition in api.filters}
    resolved_filters: list[Filter] = []
    selections: list[FilterSelection] = []
    for submitted in filters:
        compiled = definitions.get(submitted.name)
        if compiled is None:
            raise _query_error(api, "generated_api_filter_not_allowed")
        if submitted.operator not in compiled.operators:
            raise _query_error(api, "generated_api_filter_operator_not_allowed")
        try:
            resolved = resolve_filter_selection(
                compiled.filter,
                operator=submitted.operator,
                raw_value=submitted.value,
            )
        except (TypeError, ValueError) as exc:
            raise _query_error(api, "generated_api_filter_value_invalid") from exc
        resolved_filters.extend(resolved.predicates)
        selections.append(resolved.selection)

    try:
        effective_pagination = pagination or PagePagination(page=page, per_page=per_page)
        return ResourceQuery.from_components(
            sort=sort,
            pagination=effective_pagination,
            allowed_sort_fields=field_policy.sort_fields,
            identity_fields=api.identity_fields,
            filters=tuple(resolved_filters),
            filter_selections=tuple(selections),
            search=search,
            count_policy=count_policy,
        )
    except (TypeError, ValueError) as exc:
        raise _query_error(api, "generated_api_query_not_allowed") from exc


__all__ = ["GeneratedFilterValue", "build_generated_resource_query"]
