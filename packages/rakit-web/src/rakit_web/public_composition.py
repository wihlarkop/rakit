"""Validation helpers for declaration-style ResourceAdmin composition."""

from collections.abc import Collection
from http import HTTPStatus

from rakit_core.actions import ActionDefinition, ActionScope
from rakit_core.admin_types import ResourceAdmin
from rakit_core.errors import ErrorCode, RakitError
from rakit_core.relationships import RelationshipDefinition


def _invalid_declaration(admin_cls: type[ResourceAdmin], attribute: str, reason: str) -> RakitError:
    return RakitError(
        code=ErrorCode.CONFIG_INVALID,
        message=f"Invalid {admin_cls.__name__}.{attribute} declaration.",
        status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
        details={
            "admin_class": admin_cls.__name__,
            "attribute": attribute,
            "reason": reason,
        },
    )


def resource_relationships(admin_cls: type[ResourceAdmin]) -> tuple[RelationshipDefinition, ...]:
    raw = getattr(admin_cls, "relationships", ())
    if not isinstance(raw, list | tuple):
        raise _invalid_declaration(admin_cls, "relationships", "collection_required")
    relationships = tuple(raw)
    if any(not isinstance(item, RelationshipDefinition) for item in relationships):
        raise _invalid_declaration(admin_cls, "relationships", "definition_required")
    ids = tuple(str(item.relationship_id) for item in relationships)
    if len(ids) != len(set(ids)):
        raise _invalid_declaration(admin_cls, "relationships", "duplicate_relationship")
    return relationships


def resource_actions(
    admin_cls: type[ResourceAdmin],
    *,
    existing_action_ids: Collection[str] = (),
) -> tuple[ActionDefinition, ...]:
    raw = getattr(admin_cls, "actions", ())
    if not isinstance(raw, list | tuple):
        raise _invalid_declaration(admin_cls, "actions", "collection_required")
    actions = tuple(raw)
    if any(not isinstance(item, ActionDefinition) for item in actions):
        raise _invalid_declaration(admin_cls, "actions", "definition_required")
    ids = tuple(str(item.action_id) for item in actions)
    if len(ids) != len(set(ids)):
        raise _invalid_declaration(admin_cls, "actions", "duplicate_action")
    if set(ids) & set(existing_action_ids):
        raise _invalid_declaration(admin_cls, "actions", "duplicate_action")
    for action in actions:
        if action.scope is ActionScope.PAGE:
            raise _invalid_declaration(admin_cls, "actions", "page_action_not_resource_owned")
        if str(action.resource_id) != admin_cls.resource_id:
            raise _invalid_declaration(admin_cls, "actions", "resource_owner_mismatch")
    return actions


__all__ = ["resource_actions", "resource_relationships"]
