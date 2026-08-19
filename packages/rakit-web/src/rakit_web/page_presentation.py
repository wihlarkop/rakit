from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field

from rakit_web.action_presentation import (
    ActionPresentation,
    normalize_action_presentations,
)


@dataclass(frozen=True, slots=True)
class PageWebPresentation:
    """Web-only presentation configuration for one registered custom page."""

    actions: Mapping[str, ActionPresentation] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "actions",
            normalize_action_presentations(self.actions),
        )


__all__ = ["PageWebPresentation"]
