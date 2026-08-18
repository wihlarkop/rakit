from __future__ import annotations

import inspect
from collections.abc import Awaitable, Callable, Mapping
from typing import cast

from rakit_core.actions import (
    ActionAvailability,
    ActionAvailabilityDecision,
    ActionContext,
    ActionDefinition,
    resolve_availability,
)
from rakit_core.bulk import BulkSelection
from rakit_core.definitions import CompiledActionDefinition
from rakit_core.errors import RakitError
from rakit_core.forms import FormIssue
from rakit_core.mutations import OperationAuthorization
from starlette.requests import Request
from starlette.responses import Response
from starlette.routing import Route

from .action_presentation import action_web_presentation
from .action_routes import _rejected_response
from .bulk_routes import (
    BulkActionBinding,
    _bulk_context,
    _concurrency_tokens,
    _decode_selection,
    _form_args,
    _issue_confirmation,
    _load_selection,
    _owner_path,
    _selection_tokens_from_query,
    build_bulk_action_routes,
)

_EMPTY_SUBMITTED: Mapping[str, object] = {}


async def _target_context_decisions(
    binding: BulkActionBinding,
    request: Request,
    compiled: CompiledActionDefinition,
    selection: BulkSelection,
) -> tuple[tuple[ActionContext, ActionAvailabilityDecision], ...]:
    """Resolve per-target eligibility for presentation without requiring AVAILABLE."""

    decisions: list[tuple[ActionContext, ActionAvailabilityDecision]] = []
    for target in selection.targets:
        authorization = await binding.authorize_action(request, compiled, target.identity)
        if authorization is None:
            return ()
        context = _bulk_context(
            request,
            compiled.definition,
            target,
            authorization,
            submitted=_EMPTY_SUBMITTED,
            values=None,
        )
        decision = await resolve_availability(compiled.definition, context)
        decisions.append((context, decision))
    return tuple(decisions)


async def _render_review(
    binding: BulkActionBinding,
    request: Request,
    action: ActionDefinition,
    authorization: OperationAuthorization,
    *,
    route_path: str,
    owner_path: str,
    selection: BulkSelection,
    availability: str,
    availability_reason: str | None,
    issues: tuple[FormIssue, ...] = (),
    status_code: int = 200,
) -> Response:
    encoded_selection = tuple(binding.codec.encode(identity) for identity in selection.identities)
    executable = availability == "available"
    concurrency_tokens = _concurrency_tokens(binding, action, selection) if executable else ()
    policy = action.bulk_policy
    assert policy is not None
    confirmation_token = (
        _issue_confirmation(binding, request, action, authorization, selection)
        if executable
        and (action.needs_confirmation or len(selection.targets) >= policy.confirmation_threshold)
        else ""
    )
    args = _form_args(
        binding,
        request,
        action,
        route_path,
        owner_path,
        selection,
        encoded_selection,
        concurrency_tokens,
        confirmation_token,
        issues=issues,
    )
    args.update(
        {
            "action_presentation": action_web_presentation(action),
            "availability": availability,
            "availability_reason": availability_reason,
            "execution_policy": policy.execution.value,
            "synchronous_maximum": policy.synchronous_maximum,
        }
    )
    return binding.templates.TemplateResponse(
        request,
        "actions/bulk.html",
        args,
        status_code=status_code,
        headers={"Cache-Control": "no-store"},
    )


def build_mature_bulk_action_routes(binding: BulkActionBinding) -> list[Route]:
    """Wrap existing bulk POST routes while maturing selection-aware GET review."""

    original_routes = build_bulk_action_routes(binding)
    routes: list[Route] = []
    for original, (route_definition, compiled) in zip(
        original_routes,
        binding.routes,
        strict=True,
    ):
        original_endpoint = cast(
            Callable[[Request], Response | Awaitable[Response]],
            original.endpoint,
        )
        action = compiled.definition
        route_path = route_definition.path
        owner_path = _owner_path(route_definition)

        async def endpoint(
            request: Request,
            original_endpoint: Callable[
                [Request], Response | Awaitable[Response]
            ] = original_endpoint,
            action: ActionDefinition = action,
            compiled: CompiledActionDefinition = compiled,
            route_path: str = route_path,
            owner_path: str = owner_path,
        ) -> Response:
            if request.method == "POST":
                response = original_endpoint(request)
                if inspect.isawaitable(response):
                    return cast(Response, await response)
                return cast(Response, response)

            root_authorization = await binding.authorize_action(request, compiled, None)
            if root_authorization is None:
                return _rejected_response(request, "Forbidden", 403)
            try:
                identities = _decode_selection(
                    binding,
                    action,
                    _selection_tokens_from_query(request),
                )
                selection = await _load_selection(binding, identities)
            except RakitError as exc:
                return _rejected_response(request, exc.message, exc.status_code)

            decisions = await _target_context_decisions(
                binding,
                request,
                compiled,
                selection,
            )
            if len(decisions) != len(selection.targets):
                return _rejected_response(request, "Forbidden", 403)
            if any(decision.availability is ActionAvailability.HIDDEN for _, decision in decisions):
                return _rejected_response(request, "Resource was not found", 404)
            disabled = next(
                (
                    decision
                    for _, decision in decisions
                    if decision.availability is ActionAvailability.DISABLED
                ),
                None,
            )
            return await _render_review(
                binding,
                request,
                action,
                root_authorization,
                route_path=route_path,
                owner_path=owner_path,
                selection=selection,
                availability="disabled" if disabled is not None else "available",
                availability_reason=disabled.reason if disabled is not None else None,
            )

        routes.append(
            Route(
                route_path,
                endpoint,
                methods=["GET", "POST"],
                name=route_definition.route_name,
            )
        )
    return routes


__all__ = ["build_mature_bulk_action_routes"]
