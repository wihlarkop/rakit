from __future__ import annotations

import weakref
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType

from rakit_core.actions import ActionDefinition, ActionScope


class ActionIntent(StrEnum):
    """Web-only visual hierarchy for an action entry point."""

    DEFAULT = "default"
    PRIMARY = "primary"
    DANGER = "danger"


@dataclass(frozen=True, slots=True)
class ActionPresentation:
    """Web-only presentation policy for one action definition."""

    intent: ActionIntent = ActionIntent.DEFAULT

    def __post_init__(self) -> None:
        if not isinstance(self.intent, ActionIntent):
            raise TypeError("Action presentation intent must be an ActionIntent")


_DEFAULT_ACTION_PRESENTATION = ActionPresentation()
_ACTION_PRESENTATIONS: dict[
    int,
    tuple[weakref.ReferenceType[ActionDefinition], ActionPresentation],
] = {}


def normalize_action_presentations(
    values: Mapping[str, ActionPresentation],
) -> Mapping[str, ActionPresentation]:
    """Validate and freeze an action-id keyed presentation mapping."""

    normalized: dict[str, ActionPresentation] = {}
    for action_id, presentation in values.items():
        if not isinstance(action_id, str) or not action_id.strip():
            raise ValueError("Action presentation ids must be non-empty strings")
        if not isinstance(presentation, ActionPresentation):
            raise TypeError("Action presentations must contain ActionPresentation values")
        normalized[action_id] = presentation
    return MappingProxyType(normalized)


def validate_action_presentations(
    actions: Sequence[ActionDefinition],
    presentations: Mapping[str, ActionPresentation],
) -> None:
    """Validate presentation ids and primary uniqueness for one action owner."""

    declared_by_id = {str(action.action_id): action for action in actions}
    unknown_ids = sorted(set(presentations).difference(declared_by_id))
    if unknown_ids:
        raise ValueError("Unknown action presentation ids: " + ", ".join(unknown_ids))

    primary_counts: dict[ActionScope, int] = {}
    for action_id, presentation in presentations.items():
        if presentation.intent is not ActionIntent.PRIMARY:
            continue
        scope = declared_by_id[action_id].scope
        primary_counts[scope] = primary_counts.get(scope, 0) + 1
        if primary_counts[scope] > 1:
            raise ValueError(f"Only one primary {scope.value} action may be configured per owner")


def bind_action_web_presentation(
    definition: ActionDefinition,
    presentation: ActionPresentation,
) -> None:
    """Associate one exact immutable action object with its Web presentation."""

    key = id(definition)

    def cleanup(reference: weakref.ReferenceType[ActionDefinition]) -> None:
        current = _ACTION_PRESENTATIONS.get(key)
        if current is not None and current[0] is reference:
            _ACTION_PRESENTATIONS.pop(key, None)

    reference = weakref.ref(definition, cleanup)
    _ACTION_PRESENTATIONS[key] = (reference, presentation)


def action_web_presentation(definition: ActionDefinition) -> ActionPresentation:
    """Return presentation bound to this exact action definition object."""

    current = _ACTION_PRESENTATIONS.get(id(definition))
    if current is None or current[0]() is not definition:
        return _DEFAULT_ACTION_PRESENTATION
    return current[1]


__all__ = [
    "ActionIntent",
    "ActionPresentation",
    "action_web_presentation",
    "bind_action_web_presentation",
    "normalize_action_presentations",
    "validate_action_presentations",
]
