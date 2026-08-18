from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from typing import TypeAlias, cast
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
        items=tuple(
            (cast(str, key), cast(SafePageScalar, value)) for key, value in payload.items()
        ),
    )


def _table_view(payload: list[object] | tuple[object, ...]) -> PagePayloadView:
    if not payload:
        return PagePayloadView(PagePayloadKind.EMPTY)
    first = payload[0]
    if type(first) is not dict:
        return PagePayloadView(PagePayloadKind.UNSUPPORTED)
    first_row = cast(dict[object, object], first)
    raw_columns = tuple(first_row.keys())
    if not raw_columns or not all(type(key) is str and key for key in raw_columns):
        return PagePayloadView(PagePayloadKind.UNSUPPORTED)
    columns = tuple(cast(str, key) for key in raw_columns)

    rows: list[tuple[SafePageScalar, ...]] = []
    for candidate in payload:
        if type(candidate) is not dict:
            return PagePayloadView(PagePayloadKind.UNSUPPORTED)
        row = cast(dict[object, object], candidate)
        if tuple(row.keys()) != raw_columns:
            return PagePayloadView(PagePayloadKind.UNSUPPORTED)
        values = tuple(row[column] for column in raw_columns)
        if not all(_safe_scalar(value) for value in values):
            return PagePayloadView(PagePayloadKind.UNSUPPORTED)
        rows.append(tuple(cast(SafePageScalar, value) for value in values))

    return PagePayloadView(PagePayloadKind.TABLE, columns=columns, rows=tuple(rows))


def page_payload_view(payload: object) -> PagePayloadView:
    """Classify a page payload without invoking arbitrary object behavior."""

    if payload is None:
        return PagePayloadView(PagePayloadKind.EMPTY)
    if _safe_scalar(payload):
        return PagePayloadView(PagePayloadKind.SCALAR, scalar=cast(SafePageScalar, payload))
    if type(payload) is dict:
        return _mapping_view(cast(dict[object, object], payload))
    if type(payload) is list:
        return _table_view(cast(list[object], payload))
    if type(payload) is tuple:
        return _table_view(cast(tuple[object, ...], payload))
    return PagePayloadView(PagePayloadKind.UNSUPPORTED)


__all__ = ["PagePayloadKind", "PagePayloadView", "SafePageScalar", "page_payload_view"]
