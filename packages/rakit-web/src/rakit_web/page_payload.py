from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from typing import TypeAlias
from uuid import UUID

SafePageScalar: TypeAlias = str | int | float | bool | Decimal | date | datetime | UUID | None


class PagePayloadKind(StrEnum):
    EMPTY = "empty"
    SCALAR = "scalar"
    MAPPING = "mapping"
    TABLE = "table"
    UNSUPPORTED = "unsupported"


@dataclass(frozen=True, slots=True)
class PagePayloadView:
    kind: PagePayloadKind
    scalar: SafePageScalar = None
    items: tuple[tuple[str, SafePageScalar], ...] = ()
    columns: tuple[str, ...] = ()
    rows: tuple[tuple[SafePageScalar, ...], ...] = ()


_SAFE_SCALAR_TYPES = (str, int, float, bool, Decimal, date, datetime, UUID)


def _safe_scalar(value: object) -> bool:
    return value is None or type(value) in _SAFE_SCALAR_TYPES


def _mapping_view(payload: dict[object, object]) -> PagePayloadView:
    if not payload:
        return PagePayloadView(PagePayloadKind.EMPTY)
    if not all(type(key) is str and key and _safe_scalar(value) for key, value in payload.items()):
        return PagePayloadView(PagePayloadKind.UNSUPPORTED)
    return PagePayloadView(
        PagePayloadKind.MAPPING,
        items=tuple((key, value) for key, value in payload.items()),  # type: ignore[misc]
    )


def _table_view(payload: list[object] | tuple[object, ...]) -> PagePayloadView:
    if not payload:
        return PagePayloadView(PagePayloadKind.EMPTY)
    first = payload[0]
    if type(first) is not dict:
        return PagePayloadView(PagePayloadKind.UNSUPPORTED)
    first_row = first
    columns = tuple(first_row.keys())
    if not columns or not all(type(key) is str and key for key in columns):
        return PagePayloadView(PagePayloadKind.UNSUPPORTED)

    rows: list[tuple[SafePageScalar, ...]] = []
    for candidate in payload:
        if type(candidate) is not dict:
            return PagePayloadView(PagePayloadKind.UNSUPPORTED)
        row = candidate
        if tuple(row.keys()) != columns:
            return PagePayloadView(PagePayloadKind.UNSUPPORTED)
        values = tuple(row[column] for column in columns)
        if not all(_safe_scalar(value) for value in values):
            return PagePayloadView(PagePayloadKind.UNSUPPORTED)
        rows.append(values)  # type: ignore[arg-type]

    return PagePayloadView(
        PagePayloadKind.TABLE,
        columns=columns,  # type: ignore[arg-type]
        rows=tuple(rows),
    )


def page_payload_view(payload: object) -> PagePayloadView:
    """Classify a page payload without invoking arbitrary object behavior."""

    if payload is None:
        return PagePayloadView(PagePayloadKind.EMPTY)
    if _safe_scalar(payload):
        return PagePayloadView(PagePayloadKind.SCALAR, scalar=payload)  # type: ignore[arg-type]
    if type(payload) is dict:
        return _mapping_view(payload)  # type: ignore[arg-type]
    if type(payload) in {list, tuple}:
        return _table_view(payload)  # type: ignore[arg-type]
    return PagePayloadView(PagePayloadKind.UNSUPPORTED)


__all__ = ["PagePayloadKind", "PagePayloadView", "SafePageScalar", "page_payload_view"]
