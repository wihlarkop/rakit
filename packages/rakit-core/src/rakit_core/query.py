from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


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


class FilterOperator(StrEnum):
    EQ = "eq"
    NEQ = "neq"
    LT = "lt"
    LTE = "lte"
    GT = "gt"
    GTE = "gte"
    CONTAINS = "contains"
    IN = "in"
    IS_NULL = "is_null"


class Sort(BaseModel):
    model_config = ConfigDict(frozen=True)
    field: str
    direction: SortDirection = SortDirection.ASC
    nulls: NullPlacement = NullPlacement.AUTO


class Filter(BaseModel):
    model_config = ConfigDict(frozen=True)
    field: str
    operator: FilterOperator
    value: object


class OffsetPagination(BaseModel):
    model_config = ConfigDict(frozen=True)
    page: int = Field(default=1, ge=1)
    per_page: int = Field(default=25, ge=1, le=200)

    @property
    def offset(self) -> int:
        return (self.page - 1) * self.per_page


class ResourceQuery(BaseModel):
    """Immutable, typed representation of a resource listing request.

    Instances are normally produced via `from_params()`, which parses raw
    query-string-shaped input (e.g. `sort="-created_at,status"`) and enforces
    the allowed-sort-fields whitelist. Direct construction (`ResourceQuery()`)
    is also supported and yields an unfiltered, unsorted, first-page query.
    """

    model_config = ConfigDict(frozen=True)

    sorting: tuple[Sort, ...] = ()
    filters: tuple[Filter, ...] = ()
    search: str | None = None
    pagination: OffsetPagination = Field(default_factory=OffsetPagination)
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
        search: str | None = None,
        count_policy: CountPolicy = CountPolicy.EXACT,
    ) -> "ResourceQuery":
        """Parse raw query-string-shaped input into a `ResourceQuery`.

        `sort` is a comma-separated list of fields, each optionally prefixed
        with `-` for descending order (e.g. "-created_at,status"). Every
        parsed field must be present in `allowed_sort_fields`, otherwise a
        `ValueError` is raised before any `ResourceQuery` is constructed.

        After parsing explicit sort items, an ascending `Sort` is appended
        for each field in `identity_fields` not already present among the
        parsed sort fields, acting as a stable tie-breaker.
        """
        allowed = set(allowed_sort_fields)
        sort_items = cls._parse_sort(sort, allowed)

        sorted_fields = {item.field for item in sort_items}
        for field in identity_fields:
            if field not in sorted_fields:
                sort_items.append(Sort(field=field, direction=SortDirection.ASC))
                sorted_fields.add(field)

        return cls(
            sorting=tuple(sort_items),
            filters=filters,
            search=search,
            pagination=OffsetPagination(page=page, per_page=per_page),
            count_policy=count_policy,
        )

    @staticmethod
    def _parse_sort(sort: str | None, allowed: set[str]) -> list[Sort]:
        if not sort:
            return []

        items: list[Sort] = []
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

            items.append(Sort(field=field, direction=direction))

        return items


@dataclass(frozen=True)
class PageResult[T]:
    """A page of arbitrary domain records, plus pagination metadata.

    Deliberately a plain dataclass rather than a Pydantic model: `items` must
    hold arbitrary Python objects (dicts, ORM instances, etc.) as-is, without
    Pydantic attempting to validate or coerce them.
    """

    items: tuple[T, ...]
    page: int
    per_page: int
    has_previous: bool
    has_next: bool
    total_count: int | None = None
