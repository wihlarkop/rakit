"""Semantic page result foundation; rendering is owned by a later web phase."""

from dataclasses import dataclass


@dataclass(frozen=True)
class PageResult[TPagePayload]:
    payload: TPagePayload | None = None
    message: str | None = None
