from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, model_validator


class PaginationStrategy(StrEnum):
    PAGE = "page"
    LIMIT_OFFSET = "limit_offset"
    CURSOR = "cursor"


class PageSizePolicy(BaseModel):
    """Developer-controlled page-size boundary for one resource."""

    model_config = ConfigDict(frozen=True)

    default: int = 25
    allowed: tuple[int, ...] = (25, 50, 100)

    @model_validator(mode="after")
    def _validate_policy(self) -> PageSizePolicy:
        if not self.allowed:
            raise ValueError("Page-size choices must not be empty")
        if any(isinstance(value, bool) or value < 1 or value > 200 for value in self.allowed):
            raise ValueError("Page-size choices must be between 1 and 200")
        if len(set(self.allowed)) != len(self.allowed):
            raise ValueError("Page-size choices must be unique")
        if isinstance(self.default, bool) or self.default < 1 or self.default > 200:
            raise ValueError("Default page size must be between 1 and 200")
        if self.default not in self.allowed:
            raise ValueError("Default page size must be one of the allowed choices")
        return self

    def accepts(self, value: int) -> bool:
        return value in self.allowed


class ResourcePaginationPolicy(BaseModel):
    model_config = ConfigDict(frozen=True)

    strategy: PaginationStrategy = PaginationStrategy.PAGE
    size: PageSizePolicy = Field(default_factory=PageSizePolicy)


class PagePagination(BaseModel):
    """Page-number pagination request.

    This is the canonical name for the historical ``OffsetPagination``
    contract. The old public name remains an alias for source compatibility.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    page: int = Field(default=1, ge=1)
    per_page: int = Field(default=25, ge=1, le=200)

    @property
    def offset(self) -> int:
        return (self.page - 1) * self.per_page


OffsetPagination = PagePagination


class LimitOffsetPagination(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    offset: int = Field(default=0, ge=0)
    limit: int = Field(default=25, ge=1, le=200)


class CursorPagination(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    cursor: str | None = None
    limit: int = Field(default=25, ge=1, le=200)

    @model_validator(mode="after")
    def _validate_cursor(self) -> CursorPagination:
        if self.cursor is not None and not self.cursor:
            raise ValueError("Cursor must be non-empty when provided")
        return self


type ResourcePagination = PagePagination | LimitOffsetPagination | CursorPagination


@dataclass(frozen=True)
class PageResult[T]:
    items: tuple[T, ...]
    page: int
    per_page: int
    has_previous: bool
    has_next: bool
    total_count: int | None = None


@dataclass(frozen=True)
class LimitOffsetResult[T]:
    items: tuple[T, ...]
    offset: int
    limit: int
    has_previous: bool
    has_next: bool
    total_count: int | None = None


@dataclass(frozen=True)
class CursorPageResult[T]:
    items: tuple[T, ...]
    limit: int
    previous_cursor: str | None = None
    next_cursor: str | None = None


type ResourceListResult[T] = PageResult[T] | LimitOffsetResult[T] | CursorPageResult[T]


def pagination_strategy(pagination: ResourcePagination) -> PaginationStrategy:
    if isinstance(pagination, PagePagination):
        return PaginationStrategy.PAGE
    if isinstance(pagination, LimitOffsetPagination):
        return PaginationStrategy.LIMIT_OFFSET
    return PaginationStrategy.CURSOR


__all__ = [
    "CursorPageResult",
    "CursorPagination",
    "LimitOffsetPagination",
    "LimitOffsetResult",
    "OffsetPagination",
    "PagePagination",
    "PageResult",
    "PageSizePolicy",
    "PaginationStrategy",
    "ResourceListResult",
    "ResourcePagination",
    "ResourcePaginationPolicy",
    "pagination_strategy",
]
