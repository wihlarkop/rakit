def test_resource_query_configuration_types_are_publicly_reexported() -> None:
    from rakit import (
        BooleanFilter,
        ChoiceFilter,
        CursorPagination,
        DateFilter,
        DateRangeFilter,
        FilterChoice,
        FilterSelection,
        LimitOffsetPagination,
        NumberFilter,
        PagePagination,
        PageSizePolicy,
        PaginationStrategy,
        ResourceFilter,
        ResourcePaginationPolicy,
        TextFilter,
    )
    from rakit_core.filters import (
        BooleanFilter as RealBooleanFilter,
        ChoiceFilter as RealChoiceFilter,
        DateFilter as RealDateFilter,
        DateRangeFilter as RealDateRangeFilter,
        FilterChoice as RealFilterChoice,
        FilterSelection as RealFilterSelection,
        NumberFilter as RealNumberFilter,
        ResourceFilter as RealResourceFilter,
        TextFilter as RealTextFilter,
    )
    from rakit_core.pagination import (
        CursorPagination as RealCursorPagination,
        LimitOffsetPagination as RealLimitOffsetPagination,
        PagePagination as RealPagePagination,
        PageSizePolicy as RealPageSizePolicy,
        PaginationStrategy as RealPaginationStrategy,
        ResourcePaginationPolicy as RealResourcePaginationPolicy,
    )

    assert BooleanFilter is RealBooleanFilter
    assert ChoiceFilter is RealChoiceFilter
    assert CursorPagination is RealCursorPagination
    assert DateFilter is RealDateFilter
    assert DateRangeFilter is RealDateRangeFilter
    assert FilterChoice is RealFilterChoice
    assert FilterSelection is RealFilterSelection
    assert LimitOffsetPagination is RealLimitOffsetPagination
    assert NumberFilter is RealNumberFilter
    assert PagePagination is RealPagePagination
    assert PageSizePolicy is RealPageSizePolicy
    assert PaginationStrategy is RealPaginationStrategy
    assert ResourceFilter is RealResourceFilter
    assert ResourcePaginationPolicy is RealResourcePaginationPolicy
    assert TextFilter is RealTextFilter


def test_advanced_core_facade_keeps_page_compatibility_identity() -> None:
    from rakit.core import OffsetPagination, PagePagination
    from rakit_core.pagination import PagePagination as RealPagePagination

    assert OffsetPagination is RealPagePagination
    assert PagePagination is RealPagePagination
