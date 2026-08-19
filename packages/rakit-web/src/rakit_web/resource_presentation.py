from __future__ import annotations

import weakref
from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType

from rakit_core.definitions import ResourceDefinition

from rakit_web.action_presentation import (
    ActionPresentation,
    normalize_action_presentations,
)
from rakit_web.field_presentation import Presentation


@dataclass(frozen=True, slots=True)
class FilterGroupPresentation:
    """Optional Web-only behavior overrides for one semantic filter group."""

    expanded_by_default: bool | None = None
    choice_preview_count: int | None = None

    def __post_init__(self) -> None:
        if self.choice_preview_count is not None and self.choice_preview_count < 1:
            raise ValueError("Filter group choice preview count must be at least 1")


@dataclass(frozen=True, slots=True)
class FilterPanelPresentation:
    """Web-only presentation policy for a resource filter panel."""

    visible_by_default: bool = True
    collapse_after: int = 4
    choice_collapse_after: int = 8
    choice_preview_count: int = 6
    groups: Mapping[str, FilterGroupPresentation] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.collapse_after < 0:
            raise ValueError("Filter panel collapse_after must be non-negative")
        if self.choice_collapse_after < 1:
            raise ValueError("Filter choice collapse threshold must be at least 1")
        if self.choice_preview_count < 1:
            raise ValueError("Filter choice preview count must be at least 1")
        if self.choice_preview_count > self.choice_collapse_after:
            raise ValueError("Filter choice preview count cannot exceed the collapse threshold")

        normalized: dict[str, FilterGroupPresentation] = {}
        for filter_id, presentation in self.groups.items():
            if not isinstance(filter_id, str) or not filter_id.strip():
                raise ValueError("Filter presentation group ids must be non-empty strings")
            if not isinstance(presentation, FilterGroupPresentation):
                raise TypeError(
                    "Filter presentation groups must contain FilterGroupPresentation values"
                )
            normalized[filter_id] = presentation
        object.__setattr__(self, "groups", MappingProxyType(normalized))


def _normalize_presentations(
    values: Mapping[str, Presentation], *, kind: str
) -> Mapping[str, Presentation]:
    normalized: dict[str, Presentation] = {}
    for item_id, presentation in values.items():
        if not isinstance(item_id, str) or not item_id.strip():
            raise ValueError(f"{kind} presentation ids must be non-empty strings")
        if not isinstance(presentation, Presentation):
            raise TypeError(f"{kind} presentations must contain Presentation values")
        normalized[item_id] = presentation
    return MappingProxyType(normalized)


@dataclass(frozen=True, slots=True)
class ResourceWebPresentation:
    """Web-only presentation configuration for one registered resource."""

    filters: FilterPanelPresentation = field(default_factory=FilterPanelPresentation)
    actions: Mapping[str, ActionPresentation] = field(default_factory=dict)
    fields: Mapping[str, Presentation] = field(default_factory=dict)
    relationships: Mapping[str, Presentation] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "actions",
            normalize_action_presentations(self.actions),
        )
        object.__setattr__(
            self,
            "fields",
            _normalize_presentations(self.fields, kind="Field"),
        )
        object.__setattr__(
            self,
            "relationships",
            _normalize_presentations(self.relationships, kind="Relationship"),
        )


_DEFAULT_RESOURCE_WEB_PRESENTATION = ResourceWebPresentation()
_RESOURCE_PRESENTATIONS: dict[
    int,
    tuple[weakref.ReferenceType[ResourceDefinition], ResourceWebPresentation],
] = {}


def bind_resource_web_presentation(
    definition: ResourceDefinition,
    presentation: ResourceWebPresentation,
) -> None:
    """Associate one immutable compiled resource object with its Web presentation."""

    key = id(definition)

    def cleanup(reference: weakref.ReferenceType[ResourceDefinition]) -> None:
        current = _RESOURCE_PRESENTATIONS.get(key)
        if current is not None and current[0] is reference:
            _RESOURCE_PRESENTATIONS.pop(key, None)

    reference = weakref.ref(definition, cleanup)
    _RESOURCE_PRESENTATIONS[key] = (reference, presentation)


def resource_web_presentation(definition: ResourceDefinition) -> ResourceWebPresentation:
    """Return the presentation bound to this exact resource definition object."""

    current = _RESOURCE_PRESENTATIONS.get(id(definition))
    if current is None or current[0]() is not definition:
        return _DEFAULT_RESOURCE_WEB_PRESENTATION
    return current[1]


__all__ = [
    "FilterGroupPresentation",
    "FilterPanelPresentation",
    "ResourceWebPresentation",
    "bind_resource_web_presentation",
    "resource_web_presentation",
]
