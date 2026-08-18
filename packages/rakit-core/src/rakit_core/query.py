from collections.abc import Iterable, Sequence
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from .filters import Filter, FilterOperator, FilterSelection
from .pagination import (
    CursorPageResult,
    CursorPagination,
    LimitOffsetPagination,
    LimitOffsetResult,
    OffsetPagination,
    PagePagination,
    PageResult,
    PageSizePolicy,
    PaginationStrategy,
    ResourceListResult,
    ResourcePagination,
    ResourcePaginationPolicy,
)


class SortDirection(StrEnum):
    ASC = "asc"
    DESC = "desc"


class NullPlacement(StrEnum):
    AUTO = "auto"
    FIRST = "first"
    LAST = "last"


class CountPolicy(StrEnum):
    EXACT = "exact"
    DEFERRED = "deferred"
    DISABLED = "disabled"


class Sort(BaseModel):
    model_config = ConfigDict(frozen=True)
    field: str
    direction: SortDirection = SortDirection.ASC
    nulls: NullPlacement = NullPlacement.AUTO


class ResourceQuery(BaseModel):
    """Immutable, typed representation of a resource listing request.

    Instances are normally produced via `from_params()`, which preserves the
    historical page-number constructor, or `from_components()`, which accepts
    an already-validated pagination strategy. Direct construction remains
    supported and defaults to page-number pagination.

    `sorting` holds only explicit, user-requested sort columns -- the ones a
    data-source adapter validates against its resource's `sort_fields` policy.
    `identity_tie_breakers` is a separate, backend-neutral record of the
    stable identity ordering derived from `identity_fields`.

    `filter_selections` retains validated semantic request provenance for
    presentation and transport reconstruction. Data-source adapters execute
    only the flattened `filters` predicates and may ignore this field.
    """

    model_config = ConfigDict(frozen=True)

    sorting: tuple[Sort, ...] = ()
    identity_tie_breakers: tuple[Sort, ...] = ()
    filters: tuple[Filter, ...] = ()
    filter_selections: tuple[FilterSelection, ...] = ()
    search: str | None = None
    pagination: ResourcePagination = Field(default_factory=PagePagination)
    count_policy: CountPolicy = CountPolicy.EXACT

    @classmethod
    def from_params(
        cls,
        *,
        sort: str | None = None,
        page: int = 1,
        per_page: int = 25,
        allowed_sort_fields: Iterable[str],
        identity_fields: Sequence[str] = (),
        filters: tuple[Filter, ...] = (),
        filter_selections: tuple[FilterSelection, ...] = (),
        search: str | None = None,
        count_policy: CountPolicy = CountPolicy.EXACT,
    ) -> "ResourceQuery":
        """Compatibility constructor for page-number resource queries."""
        return cls.from_components(
            sort=sort,
            pagination=PagePagination(page=page, per_page=per_page),
            allowed_sort_fields=allowed_sort_fields,
            identity_fields=identity_fields,
            filters=filters,
            filter_selections=filter_selections,
            search=search,
            count_policy=count_policy,
        )

    @classmethod
    def from_components(
        cls,
        *,
        pagination: ResourcePagination,
        allowed_sort_fields: Iterable[str],
        sort: str | None = None,
        identity_fields: Sequence[str] = (),
        filters: tuple[Filter, ...] = (),
        filter_selections: tuple[FilterSelection, ...] = (),
        search: str | None = None,
        count_policy: CountPolicy = CountPolicy.EXACT,
    ) -> "ResourceQuery":
        allowed = set(allowed_sort_fields)
        sort_items = cls._parse_sort(sort, allowed)

        if search is not None:
            search = search.strip() or None

        sorted_fields = {item.field for item in sort_items}
        tie_breakers: list[Sort] = []
        for field in identity_fields:
            if field not in sorted_fields:
                tie_breakers.append(Sort(field=field, direction=SortDirection.ASC))
                sorted_fields.add(field)

        return cls(
            sorting=tuple(sort_items),
            identity_tie_breakers=tuple(tie_breakers),
            filters=filters,
            filter_selections=filter_selections,
            search=search,
            pagination=pagination,
            count_policy=count_policy,
        )

    @staticmethod
    def _parse_sort(sort: str | None, allowed: set[str]) -> list[Sort]:
        if not sort:
            return []

        items: list[Sort] = []
        seen: dict[str, SortDirection] = {}
        for raw_field in sort.split(","):
            token = raw_field.strip()
            if not token:
                continue

            if token.startswith("-"):
                field, direction = token[1:], SortDirection.DESC
            else:
                field, direction = token, SortDirection.ASC

            if field not in allowed:
                raise ValueError(f"Sort field {field!r} is not allowed")

            existing_direction = seen.get(field)
            if existing_direction is not None:
                if existing_direction is not direction:
                    raise ValueError(f"Contradictory sort field {field!r}")
                continue

            items.append(Sort(field=field, direction=direction))
            seen[field] = direction

        return items


__all__ = [
    "CountPolicy",
    "CursorPageResult",
    "CursorPagination",
    "Filter",
    "FilterOperator",
    "FilterSelection",
    "LimitOffsetPagination",
    "LimitOffsetResult",
    "NullPlacement",
    "OffsetPagination",
    "PagePagination",
    "PageResult",
    "PageSizePolicy",
    "PaginationStrategy",
    "ResourceListResult",
    "ResourcePagination",
    "ResourcePaginationPolicy",
    "ResourceQuery",
    "Sort",
    "SortDirection",
]
