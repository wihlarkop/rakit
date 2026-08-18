from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass

from rakit_core.actions import (
    ActionAvailability,
    ActionContext,
    ActionScope,
    resolve_availability,
)
from rakit_core.auth import Principal
from rakit_core.definitions import CompiledActionDefinition, RouteDefinition
from rakit_core.identity import IdentityCodec, RecordIdentity
from rakit_core.mutations import OperationAuthorization
from starlette.requests import Request

from ._paths import mounted_path
from .action_presentation import ActionIntent, action_web_presentation


@dataclass(frozen=True, slots=True)
class ActionView:
    action_id: str
    label: str
    url: str
    intent: ActionIntent
    availability: ActionAvailability
    reason: str | None = None


ActionViewProvider = Callable[
    [Request, str, ActionScope, RecordIdentity | None, object | None],
    Awaitable[tuple[ActionView, ...]],
]

_ACTION_VIEW_PROVIDER_STATE = "rakit_action_view_provider"


def _principal(request: Request) -> Principal | None:
    state = request.scope.get("state", {})
    if not isinstance(state, Mapping):
        return None
    principal = state.get("principal")
    return principal if isinstance(principal, Principal) else None


def _owner_id(compiled: CompiledActionDefinition) -> str:
    definition = compiled.definition
    owner = definition.page_id if definition.scope is ActionScope.PAGE else definition.resource_id
    return str(owner) if owner is not None else ""


def _route_url(
    request: Request,
    route: RouteDefinition,
    scope: ActionScope,
    identity: RecordIdentity | None,
) -> str:
    path = route.path
    if scope is ActionScope.RECORD:
        if identity is None:
            raise ValueError("RECORD action views require a record identity")
        path = path.replace("{identity}", IdentityCodec().encode(identity))
    return mounted_path(request, path)


async def resolve_action_views(
    *,
    request: Request,
    routes: tuple[tuple[RouteDefinition, CompiledActionDefinition], ...],
    admin_id: str,
    owner_id: str,
    scope: ActionScope,
    superuser_bypass: bool,
    identity: RecordIdentity | None = None,
    record: object | None = None,
) -> tuple[ActionView, ...]:
    """Resolve permission- and availability-aware action entry points."""

    principal = _principal(request)
    if principal is None or not principal.authenticated or principal.subject_id is None:
        return ()

    views: list[ActionView] = []
    for route, compiled in routes:
        definition = compiled.definition
        if definition.scope is not scope or _owner_id(compiled) != owner_id:
            continue
        if not compiled.permission.matches(
            principal,
            superuser_bypass=superuser_bypass,
        ):
            continue

        authorization = OperationAuthorization.for_requirement(
            admin_id=admin_id,
            resource_id=owner_id,
            operation=f"action:{definition.action_id}",
            principal_id=principal.subject_id,
            requirement=compiled.permission,
            target_identity=identity,
        )
        context = ActionContext(
            definition=definition,
            scope=scope,
            identity=identity,
            record=record,
            authorization=authorization,
            principal=principal,
        )
        decision = await resolve_availability(definition, context)
        if decision.availability is ActionAvailability.HIDDEN:
            continue
        presentation = action_web_presentation(definition)
        views.append(
            ActionView(
                action_id=str(definition.action_id),
                label=str(definition.label),
                url=_route_url(request, route, scope, identity),
                intent=presentation.intent,
                availability=decision.availability,
                reason=decision.reason,
            )
        )
    return tuple(views)


async def request_action_views(
    request: Request,
    *,
    owner_id: str,
    scope: ActionScope,
    identity: RecordIdentity | None = None,
    record: object | None = None,
) -> tuple[ActionView, ...]:
    """Use the public Admin facade's request-local action view provider when present."""

    state = request.scope.get("state", {})
    if not isinstance(state, Mapping):
        return ()
    provider = state.get(_ACTION_VIEW_PROVIDER_STATE)
    if not callable(provider):
        return ()
    return await provider(request, owner_id, scope, identity, record)


__all__ = [
    "ActionView",
    "ActionViewProvider",
    "request_action_views",
    "resolve_action_views",
]
