"""Small semantic helpers shared by the built-in UI runtime."""

from __future__ import annotations

import re

_UNSAFE_DOM_TOKEN = re.compile(r"[^a-zA-Z0-9_-]")


def safe_dom_token(value: object) -> str:
    """Return a deterministic token that is safe inside an HTML id.

    This deliberately preserves length and separators instead of hashing so
    rendered markup remains understandable to developers and assistive-tool
    diagnostics.
    """

    return _UNSAFE_DOM_TOKEN.sub("-", str(value))


def describedby_ids(*values: str | None) -> str | None:
    """Join present description/error ids for ``aria-describedby``."""

    present = tuple(value for value in values if value)
    return " ".join(present) if present else None


__all__ = ["describedby_ids", "safe_dom_token"]
