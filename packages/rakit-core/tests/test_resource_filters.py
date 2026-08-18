from __future__ import annotations

from datetime import date

import pytest
from pydantic import ValidationError
from rakit_core.compiler import ApplicationBuilder, compile_application
from rakit_core.datasource import DataSourceCapabilities
from rakit_core.definitions import ResourceDefinition, ResourceFieldPolicy
from rakit_core.errors import RakitError
from rakit_core.filters import (
    BooleanFilter,
    ChoiceFilter,
    DateFilter,
    Filter,
    FilterChoice,
    FilterControl,
    FilterOperator,
    LegacyFieldFilter,
    NumberFilter,
    ResourceFilter,
    TextFilter,
    effective_resource_filters,
    resolve_filter_selection,
)
from rakit_core.generated_api import ApiExposure, ApiFilterDefinition, ResourceApiDefinition
from rakit_core.generated_query import GeneratedFilterValue, build_generated_resource_query
from rakit_core.identity import RecordIdentity
from rakit_core.pagination import (
    CursorPagination,
    LimitOffsetPagination,
    OffsetPagination,
    PagePagination,
    PageResult,
    PageSizePolicy,
    PaginationStrategy,
    ResourcePaginationPolicy,
)
from rakit_core.query import ResourceQuery


class RiskBandFilter(ResourceFilter):
    control: FilterControl = FilterControl.TEXT

    def parse_value(self, *, operator: FilterOperator, raw_value: object) -> object:
        if not isinstance(raw_value, str) or ":" not in raw_value:
            raise ValueError("Risk band must be min:max")
        minimum, maximum = raw_value.split(":", 1)
        return (minimum, maximum)

    def resolve_predicates(
        self,
        *,
        operator: FilterOperator,
        value: object,
    ) -> tuple[Filter, ...]:
        assert isinstance(value, tuple)
        minimum, maximum = value
        return (
            Filter(field="risk_min", operator=FilterOperator.GTE, value=minimum),
            Filter(field="risk_max", operator=FilterOperator.LTE, value=maximum),
        )


class UndeclaredPredicateFilter(ResourceFilter):
    control: FilterControl = FilterControl.TEXT

    def resolve_predicates(
        self,
        *,
        operator: FilterOperator,
        value: object,
    ) -> tuple[Filter, ...]:
        return (Filter(field="secret", operator=operator, value=value),)


class FakeDataSource:
    capabilities = DataSourceCapabilities(read=True)
    fields = ("id", "status", "internal_risk", "risk_min", "risk_max")
    identity_fields = ("id",)

    async def list(self, query: ResourceQuery) -> PageResult[dict[str, object]]:
        del query
        return PageResult((), 1, 25, False, False, 0)

    async def count(self, query: ResourceQuery) -> int:
        del query
        return 0

    async def detail(self, identity: RecordIdentity) -> object | None:
        del identity
        return None


def _resource(
    *,
    filters: tuple[ResourceFilter, ...] = (),
    api: ResourceApiDefinition | None = None,
    pagination: ResourcePaginationPolicy | None = None,
) -> ResourceDefinition:
    return ResourceDefinition(
        resource_id="orders",
        path="/orders",
        label="Orders",
        singular_label="Order",
        field_policy=ResourceFieldPolicy(
            list_fields=("id", "status"),
            detail_fields=("id", "status", "internal_risk", "risk_min", "risk_max"),
            filter_fields=("status",),
            sort_fields=("id",),
        ),
        filters=filters,
        pagination=pagination or ResourcePaginationPolicy(),
        api=api or ResourceApiDefinition(),
    )


def test_builtin_filter_validation_and_value_parsing() -> None:
    status = ChoiceFilter(
        filter_id="status",
        label="Status",
        field="status",
        choices=(FilterChoice(value="paid", label="Paid"),),
    )
    resolved = resolve_filter_selection(status, operator=FilterOperator.EQ, raw_value="paid")
    assert resolved.selection.filter_id == "status"
    assert resolved.display_value == "Paid"
    assert resolved.predicates == (
        Filter(field="status", operator=FilterOperator.EQ, value="paid"),
    )

    assert resolve_filter_selection(
        BooleanFilter(filter_id="active", label="Active", field="status"),
        operator=FilterOperator.EQ,
        raw_value="true",
    ).selection.value is True
    assert resolve_filter_selection(
        NumberFilter(filter_id="score", label="Score", field="risk_min"),
        operator=FilterOperator.GTE,
        raw_value="10.50",
    ).selection.value == "10.50"
    assert resolve_filter_selection(
        DateFilter(filter_id="created", label="Created", field="status"),
        operator=FilterOperator.EQ,
        raw_value=date(2026, 8, 18),
    ).selection.value == "2026-08-18"

    with pytest.raises(ValueError):
        resolve_filter_selection(status, operator=FilterOperator.EQ, raw_value="unknown")
    with pytest.raises(ValueError):
        resolve_filter_selection(status, operator=FilterOperator.CONTAINS, raw_value="paid")


def test_custom_filter_resolves_to_multiple_and_predicates_with_provenance() -> None:
    definition = RiskBandFilter(
        filter_id="risk_band",
        label="Risk band",
        predicate_fields=("risk_min", "risk_max"),
    )
    resolved = resolve_filter_selection(
        definition,
        operator=FilterOperator.EQ,
        raw_value="10:20",
    )
    query = ResourceQuery.from_components(
        pagination=PagePagination(),
        allowed_sort_fields={"id"},
        filters=resolved.predicates,
        filter_selections=(resolved.selection,),
    )

    assert [(item.field, item.operator, item.value) for item in query.filters] == [
        ("risk_min", FilterOperator.GTE, "10"),
        ("risk_max", FilterOperator.LTE, "20"),
    ]
    assert query.filter_selections == (resolved.selection,)


def test_custom_filter_cannot_emit_undeclared_predicate_field() -> None:
    definition = UndeclaredPredicateFilter(
        filter_id="safe",
        label="Safe",
        predicate_fields=("status",),
    )
    with pytest.raises(ValueError, match="undeclared predicate"):
        resolve_filter_selection(definition, operator=FilterOperator.EQ, raw_value="x")


@pytest.mark.parametrize(
    "factory",
    (
        lambda: TextFilter(filter_id="", label="Name", field="status"),
        lambda: TextFilter(filter_id="name", label="", field="status"),
        lambda: ChoiceFilter(filter_id="status", label="Status", field="status", choices=()),
        lambda: ChoiceFilter(
            filter_id="status",
            label="Status",
            field="status",
            choices=(
                FilterChoice(value="paid", label="Paid"),
                FilterChoice(value="paid", label="Duplicate"),
            ),
        ),
        lambda: TextFilter(
            filter_id="name",
            label="Name",
            field="status",
            operators=(FilterOperator.EQ, FilterOperator.EQ),
        ),
    ),
)
def test_invalid_filter_definitions_fail_closed(factory) -> None:
    with pytest.raises(ValidationError):
        factory()


def test_explicit_filter_overrides_same_named_legacy_filter() -> None:
    explicit = ChoiceFilter(
        filter_id="status",
        label="Order status",
        field="status",
        choices=(FilterChoice(value="paid", label="Paid"),),
    )
    effective = effective_resource_filters((explicit,), ("status", "internal_risk"))
    assert effective[0] is explicit
    assert [item.filter_id for item in effective] == ["status", "internal_risk"]
    assert isinstance(effective[1], LegacyFieldFilter)


def test_legacy_filter_fields_preserve_field_operator_and_in_semantics() -> None:
    (legacy,) = effective_resource_filters((), ("status",))
    assert isinstance(legacy, LegacyFieldFilter)
    assert legacy.filter_id == "status"
    assert legacy.field == "status"
    assert set(legacy.operators) == set(FilterOperator)
    resolved = resolve_filter_selection(
        legacy,
        operator=FilterOperator.IN,
        raw_value="paid,pending",
    )
    assert resolved.selection.value == ("paid", "pending")
    assert resolved.predicates[0].field == "status"


def test_resource_rejects_duplicate_explicit_filter_ids() -> None:
    first = TextFilter(filter_id="status", label="Status", field="status")
    second = TextFilter(filter_id="status", label="Other", field="status")
    with pytest.raises(ValidationError, match="filter ids must be unique"):
        _resource(filters=(first, second))


def test_pagination_contracts_and_compatibility_alias() -> None:
    assert OffsetPagination is PagePagination
    assert PageSizePolicy() == PageSizePolicy(default=25, allowed=(25, 50, 100))
    assert PagePagination(page=2, per_page=25).offset == 25
    assert LimitOffsetPagination(offset=25, limit=50).offset == 25
    assert CursorPagination(cursor="opaque", limit=25).cursor == "opaque"

    with pytest.raises(ValidationError):
        PageSizePolicy(allowed=())
    with pytest.raises(ValidationError):
        PageSizePolicy(default=10, allowed=(25, 50))
    with pytest.raises(ValidationError):
        PageSizePolicy(default=25, allowed=(25, 25))
    with pytest.raises(ValidationError):
        PageSizePolicy(default=25, allowed=(0, 25))


def test_resource_query_constructs_each_pagination_strategy() -> None:
    for pagination in (
        PagePagination(page=2, per_page=25),
        LimitOffsetPagination(offset=25, limit=25),
        CursorPagination(cursor="next", limit=25),
    ):
        query = ResourceQuery.from_components(
            pagination=pagination,
            allowed_sort_fields={"id"},
            sort="id",
        )
        assert query.pagination == pagination


def test_data_source_capability_rejects_unsupported_pagination_strategy() -> None:
    builder = ApplicationBuilder()
    definition = _resource(
        pagination=ResourcePaginationPolicy(strategy=PaginationStrategy.LIMIT_OFFSET)
    )
    with pytest.raises(RakitError) as captured:
        builder.add_resource(definition, FakeDataSource())
    assert captured.value.details == {
        "resource_id": "orders",
        "reason": "pagination_strategy_not_supported",
        "strategy": "limit_offset",
    }


def test_generated_api_reuses_shared_filter_and_does_not_auto_expose_admin_only_filter() -> None:
    status = ChoiceFilter(
        filter_id="status",
        label="Status",
        field="status",
        choices=(FilterChoice(value="paid", label="Paid"),),
    )
    internal = TextFilter(
        filter_id="internal_risk",
        label="Internal risk",
        field="internal_risk",
    )
    builder = ApplicationBuilder()
    builder.add_resource(
        _resource(
            filters=(status, internal),
            api=ResourceApiDefinition(exposure=ApiExposure.READ_ONLY, filters=("status",)),
        ),
        FakeDataSource(),
    )
    compiled = compile_application(builder).compiled_resource_apis[0]
    assert compiled.filters[0].filter == status

    query = build_generated_resource_query(
        compiled,
        _resource().field_policy,
        filters=(GeneratedFilterValue("status", FilterOperator.EQ, "paid"),),
    )
    assert query.filters == (Filter(field="status", operator=FilterOperator.EQ, value="paid"),)

    with pytest.raises(RakitError) as captured:
        build_generated_resource_query(
            compiled,
            _resource().field_policy,
            filters=(
                GeneratedFilterValue("internal_risk", FilterOperator.EQ, "secret"),
            ),
        )
    assert captured.value.details["reason"] == "generated_api_filter_not_allowed"


def test_generated_api_unknown_filter_id_fails_compile_and_legacy_direct_definition_survives() -> None:
    unknown = ApplicationBuilder()
    unknown.add_resource(
        _resource(
            api=ResourceApiDefinition(exposure=ApiExposure.READ_ONLY, filters=("missing",))
        ),
        FakeDataSource(),
    )
    with pytest.raises(RakitError) as captured:
        compile_application(unknown)
    assert captured.value.details["reason"] == "generated_api_filter_not_found"

    legacy = ApplicationBuilder()
    legacy.add_resource(
        _resource(
            api=ResourceApiDefinition(
                exposure=ApiExposure.READ_ONLY,
                filters=(
                    ApiFilterDefinition(
                        name="state",
                        field="status",
                        operators=(FilterOperator.EQ, FilterOperator.IN),
                    ),
                ),
            )
        ),
        FakeDataSource(),
    )
    compiled = compile_application(legacy).compiled_resource_apis[0]
    query = build_generated_resource_query(
        compiled,
        _resource().field_policy,
        filters=(GeneratedFilterValue("state", FilterOperator.IN, "paid, pending"),),
    )
    assert query.filters[0].value == ("paid", "pending")


def test_custom_semantic_filter_resolves_identically_for_generated_api() -> None:
    risk = RiskBandFilter(
        filter_id="risk_band",
        label="Risk band",
        predicate_fields=("risk_min", "risk_max"),
    )
    expected = resolve_filter_selection(
        risk,
        operator=FilterOperator.EQ,
        raw_value="10:20",
    )

    builder = ApplicationBuilder()
    builder.add_resource(
        _resource(
            filters=(risk,),
            api=ResourceApiDefinition(exposure=ApiExposure.READ_ONLY, filters=("risk_band",)),
        ),
        FakeDataSource(),
    )
    compiled = compile_application(builder).compiled_resource_apis[0]
    query = build_generated_resource_query(
        compiled,
        _resource().field_policy,
        filters=(GeneratedFilterValue("risk_band", FilterOperator.EQ, "10:20"),),
    )
    assert query.filters == expected.predicates
    assert query.filter_selections == (expected.selection,)

    with pytest.raises(RakitError) as captured:
        build_generated_resource_query(
            compiled,
            _resource().field_policy,
            filters=(GeneratedFilterValue("risk_band", FilterOperator.EQ, "invalid"),),
        )
    assert captured.value.details["reason"] == "generated_api_filter_value_invalid"
