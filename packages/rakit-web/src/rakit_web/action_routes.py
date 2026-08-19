"""Web translation of unified actions.

GET resolves the action, authorizes invocation, scoped-loads the record for
RECORD actions, evaluates availability, and renders the appropriate form,
preview, or confirmation state without mutating data.

POST re-runs the entire boundary against freshly loaded state: CSRF, exact
action authorization, scoped record reload, strict input parsing,
confirmation verification, availability recheck, concurrency, idempotency,
and finally execution inside the established operation context.  Availability
is never a substitute for authorization, and vice versa.

The full-page flow works without JavaScript; HTMX is a presentation-only
enhancement of the same pipeline.
"""
from http import HTTPStatus

import hashlib
import inspect
import json
from collections.abc import Awaitable, Callable, Mapping
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from datetime import timedelta
from html import escape
from typing import Any

import anyio
from pydantic import TypeAdapter
from rakit_core.actions import (
    ActionAdvancedResponse,
    ActionAvailability,
    ActionAvailabilityDecision,
    ActionContext,
    ActionDefinition,
    ActionRedirect,
    ActionRefresh,
    ActionRejected,
    ActionRendered,
    ActionResult,
    ActionScope,
    ActionSuccess,
    ActionValidation,
    build_action_operation_plan,
    resolve_availability,
    resolve_preview,
)
from rakit_core.compiler import RESOURCE_ACTION_SEGMENT
from rakit_core.concurrency import ConcurrencyTokenService
from rakit_core.crypto import TokenService
from rakit_core.definitions import CompiledActionDefinition, RouteDefinition
from rakit_core.di import ServiceResolver
from rakit_core.errors import ErrorCode, RakitError
from rakit_core.events import EventPublisher
from rakit_core.forms import FormIssue, FormSchema, FormState, FormValidationError
from rakit_core.idempotency import (
    IdempotencyReservation,
    IdempotencyStatus,
    IdempotencyStore,
    OperationReceipt,
)
from rakit_core.identity import IdentityCodec, RecordIdentity
from rakit_core.mutations import OperationAuthorization
from rakit_core.operations import (
    CancellationContext,
    Deadline,
    OperationContext,
    OperationPlan,
    activate_operation_context,
    new_operation_id,
    run_operation_plan,
    run_with_deadline,
)
from rakit_core.transactions import OperationUnitOfWorkFactory, TransactionPolicy
from starlette.requests import Request
from starlette.responses import HTMLResponse, RedirectResponse, Response
from starlette.routing import Route
from starlette.templating import Jinja2Templates

from ._paths import mounted_path
from .results import mutation_success
from .security.cookies import CSRF_COOKIE_NAME

_CONFIRMATION_TTL = timedelta(minutes=15)
_MAX_ACTION_FIELDS = 500

type AdvancedActionResponseAdapter = Callable[
    [Request, ActionAdvancedResponse], Response | Awaitable[Response]
]


async def _fail_final_reservation(
    store: IdempotencyStore,
    reservation: IdempotencyReservation,
) -> None:
    with anyio.CancelScope(shield=True):
        await store.fail_final(reservation)


@dataclass(frozen=True)
class ActionBinding:
    """Web adapters for one owner's compiled action routes.

    ``routes`` carries compiler-owned pairs: the neutral ``RouteDefinition``
    (path, method contract, stable route name, owner) plus the compiled
    action with its authoritative resolved permission.  Starlette
    materialization invents no independent URL, method, permission, or
    route-name grammar for actions.
    """

    routes: tuple[tuple[RouteDefinition, CompiledActionDefinition], ...]
    templates: Jinja2Templates
    codec: IdentityCodec
    verify_csrf: Callable[[Request], Awaitable[bool]]
    verify_submission_token: Callable[[Request], Awaitable[bool]]
    issue_submission_token: Callable[[Request], str]
    authorize_action: Callable[
        [Request, CompiledActionDefinition, RecordIdentity | None],
        Awaitable[OperationAuthorization | None],
    ]
    load_record: Callable[[RecordIdentity], Awaitable[object | None]] | None = None
    record_version: Callable[[object], object] | None = None
    concurrency: ConcurrencyTokenService | None = None
    concurrency_resource_id: str | None = None
    token_service: TokenService | None = None
    idempotency_store: IdempotencyStore | None = None
    deadline_seconds: float | None = None
    operation_scope: Callable[[], AbstractAsyncContextManager[ServiceResolver]] | None = None
    unit_of_work_factory: Callable[[], OperationUnitOfWorkFactory | None] | None = None
    advanced_response_adapter: AdvancedActionResponseAdapter | None = None
    label: str = "Actions"

    def __post_init__(self) -> None:
        for route, compiled_action in self.routes:
            action = compiled_action.definition
            if action.scope is ActionScope.BULK:
                raise ValueError("BULK actions require a bulk action binding")
            if route.methods != ("GET", "POST"):
                raise ValueError(f"Action route {route.route_name!r} must declare GET and POST")
            if action.scope is ActionScope.RECORD:
                if "{identity}" not in route.path:
                    raise ValueError("RECORD action routes require an {identity} path")
                if self.load_record is None:
                    raise ValueError("RECORD action routes require a scoped record loader")
            elif "{identity}" in route.path:
                raise ValueError(
                    f"{action.scope.value} action routes must not contain {{identity}}"
                )
            if action.needs_confirmation and self.token_service is None:
                raise ValueError(f"Action {action.action_id!r} requires confirmation token support")
            if action.requires_concurrency and (
                self.concurrency is None
                or self.concurrency_resource_id is None
                or self.record_version is None
            ):
                raise ValueError(f"Action {action.action_id!r} requires concurrency support")


def _owner_path(route: RouteDefinition) -> str:
    """The logical owner destination of a compiler-owned action route.

    The canonical grammar is ``{owner_path}/{_actions}/{action_id}`` for
    RESOURCE, RECORD, and PAGE action routes; the owner destination is the
    prefix before the ``/_actions/`` segment (e.g. ``/orders/{identity}``
    for ``/orders/{identity}/_actions/approve``).  A root owner ("/") yields
    "/" so framework-generated destinations are never empty.
    """
    owner_path, separator, _ = route.path.rpartition(f"/{RESOURCE_ACTION_SEGMENT}/")
    if not separator:
        raise ValueError(
            f"Action route {route.route_name!r} must live under /{RESOURCE_ACTION_SEGMENT}/"
        )
    return owner_path or "/"


def _with_identity(binding: ActionBinding, identity: RecordIdentity | None, path: str) -> str:
    if identity is None:
        return path
    return path.replace("{identity}", binding.codec.encode(identity))


def _action_fingerprint(
    action_id: str, identity: RecordIdentity | None, submitted: Mapping[str, object]
) -> str:
    payload = {
        "action_id": action_id,
        "identity": dict(identity.values) if identity is not None else None,
        "input": dict(sorted(submitted.items())),
    }
    encoded = json.dumps(payload, sort_keys=True, default=str, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _confirmation_input_fingerprint(
    schema: FormSchema | None,
    state: FormState | None,
) -> str:
    canonical: dict[str, object] = {}
    if schema is not None and state is not None:
        fields = {field.field_id: field for field in schema.fields}
        for field_id in sorted(state.normalized):
            field = fields[field_id]
            value = state.normalized[field_id]
            canonical[field_id] = (
                None
                if value is None
                else TypeAdapter(field.python_type).dump_python(value, mode="json")
            )
    encoded = json.dumps(canonical, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _session_id(request: Request) -> str:
    state = request.scope.get("state", {})
    if not isinstance(state, Mapping):
        return ""
    session_id = state.get("session_id")
    return session_id if isinstance(session_id, str) else ""


def _confirmation_claims(
    request: Request,
    action: ActionDefinition,
    identity: RecordIdentity | None,
    authorization: OperationAuthorization,
    input_fingerprint: str,
) -> dict[str, object]:
    owner_id = action.page_id if action.scope is ActionScope.PAGE else action.resource_id
    return {
        "admin_id": authorization.admin_id,
        "scope": action.scope.value,
        "owner_id": owner_id,
        "action_id": action.action_id,
        "identity": dict(identity.values) if identity is not None else None,
        "principal_id": authorization.principal_id,
        "session_id": _session_id(request),
        "input_fingerprint": input_fingerprint,
    }


def _identity(
    binding: ActionBinding, request: Request, action: ActionDefinition
) -> RecordIdentity | None:
    if action.scope is not ActionScope.RECORD:
        return None
    encoded = request.path_params.get("identity")
    if not isinstance(encoded, str):
        raise RakitError(
            code=ErrorCode.VALIDATION_FAILED,
            message="Invalid resource identity",
            status_code=HTTPStatus.BAD_REQUEST,
        )
    try:
        return binding.codec.decode(encoded)
    except ValueError as exc:
        raise RakitError(
            code=ErrorCode.VALIDATION_FAILED,
            message="Invalid resource identity",
            status_code=HTTPStatus.BAD_REQUEST,
        ) from exc


def _field_views(
    schema: FormSchema | None,
    submitted: Mapping[str, object],
    issues: tuple[FormIssue, ...],
) -> tuple[dict[str, object], ...]:
    issue_map: dict[str, tuple[FormIssue, ...]] = {}
    for issue in issues:
        if isinstance(issue.field_id, str):
            issue_map[issue.field_id] = (*issue_map.get(issue.field_id, ()), issue)
    views = []
    for field in schema.fields if schema is not None else ():
        if not field.writable or not field.readable or field.sensitive:
            continue
        field_id = field.field_id
        views.append(
            {
                "id": f"rakit-action-{field_id}",
                "name": field_id,
                "label": field.label or field_id,
                "description": field.description,
                "description_id": f"rakit-action-{field_id}-description",
                "error_id": f"rakit-action-{field_id}-error",
                "value": submitted.get(field_id, ""),
                "issues": issue_map.get(field_id, ()),
            }
        )
    return tuple(views)


def _action_context(
    binding: ActionBinding,
    request: Request,
    action: ActionDefinition,
    *,
    identity: RecordIdentity | None,
    record: object | None,
    authorization: OperationAuthorization,
    submitted: Mapping[str, object] = {},
    values: Any = None,
    availability: ActionAvailabilityDecision | None = None,
    concurrency_token: str | None = None,
    confirmation_token: str | None = None,
) -> ActionContext:
    return ActionContext(
        definition=action,
        scope=action.scope,
        identity=identity,
        record=record,
        submitted=submitted,
        values=values,
        authorization=authorization,
        availability=availability
        or ActionAvailabilityDecision(availability=ActionAvailability.AVAILABLE),
        principal=request.scope.get("state", {}).get("principal"),
        concurrency_token=concurrency_token,
        confirmation_token=confirmation_token,
    )


async def _run_action_operation(
    binding: ActionBinding,
    request: Request,
    plan: OperationPlan[ActionContext, ActionResult[Any]],
    authorization: OperationAuthorization,
) -> ActionResult[Any]:
    """Execute one prepared action operation at the canonical seam.

    Enters the request + operation service scopes (when the binding has an
    operation scope), populates the full ``OperationContext`` from request
    and authorization state, activates it, and runs the plan through the core
    operation lifecycle runner -- AUTO/MANUAL transaction semantics belong to
    core, never to the web layer.  Deadline behavior is preserved via
    ``run_with_deadline``.
    """
    deadline = (
        Deadline.after(binding.deadline_seconds) if binding.deadline_seconds is not None else None
    )
    request_state = request.scope.get("state", {})
    request_state = request_state if isinstance(request_state, Mapping) else {}
    session_id = request_state.get("session_id")
    if not isinstance(session_id, str):
        session_id = ""
    services: ServiceResolver | None = None
    events: EventPublisher | None = None

    async def run_with_services() -> ActionResult[Any]:
        nonlocal services, events
        needs_uow = plan.mutating and plan.transaction_policy in (
            TransactionPolicy.AUTO,
            TransactionPolicy.MANUAL,
        )
        unit_of_work_factory = (
            binding.unit_of_work_factory()
            if needs_uow and binding.unit_of_work_factory is not None
            else None
        )
        context = OperationContext(
            deadline=deadline,
            cancellation=CancellationContext(),
            request_id=str(request_state.get("request_id", "")),
            operation_id=new_operation_id(),
            principal=request_state.get("principal"),
            principal_id=authorization.principal_id,
            session_id=session_id,
            admin_id=authorization.admin_id,
            resource_id=authorization.resource_id,
            operation=authorization.operation,
            permissions=authorization.permissions,
            permission_requirement=authorization.requirement,
            services=services,
            events=events,
        )
        with activate_operation_context(context):
            context.checkpoint()
            if deadline is None:
                return await run_operation_plan(
                    plan, context, unit_of_work_factory=unit_of_work_factory
                )
            return await run_with_deadline(
                run_operation_plan(plan, context, unit_of_work_factory=unit_of_work_factory),
                deadline,
            )

    if binding.operation_scope is not None:
        async with binding.operation_scope() as operation_services:
            services = operation_services
            events = operation_services.require(EventPublisher)
            return await run_with_services()
    return await run_with_services()


def _action_result_response(
    request: Request,
    result: ActionResult[Any],
    *,
    fallback_location: str,
) -> Response:
    if isinstance(result, ActionSuccess):
        return mutation_success(
            request,
            location=fallback_location,
            refresh_targets=("rakit:action-refresh",),
            message=result.message,
        )
    if isinstance(result, ActionRedirect):
        if request.headers.get("HX-Request") == "true":
            return Response(
                status_code=HTTPStatus.NO_CONTENT,
                headers={"HX-Redirect": result.location, "Cache-Control": "no-store"},
            )
        return RedirectResponse(
            result.location, status_code=HTTPStatus.SEE_OTHER, headers={"Cache-Control": "no-store"}
        )
    if isinstance(result, ActionRefresh):
        if request.headers.get("HX-Request") == "true":
            trigger: dict[str, object] = {"rakit:refresh": {"targets": [result.target]}}
            if result.message:
                trigger["rakit:toast"] = {"message": result.message}
            return Response(
                status_code=HTTPStatus.NO_CONTENT,
                headers={"HX-Trigger": json.dumps(trigger), "Cache-Control": "no-store"},
            )
        return RedirectResponse(
            fallback_location, status_code=HTTPStatus.SEE_OTHER, headers={"Cache-Control": "no-store"}
        )
    if isinstance(result, ActionRejected):
        return _rejected_response(request, result.message or "Action rejected", 409)
    if isinstance(result, ActionRendered):
        return HTMLResponse(
            result.fragment,
            status_code=HTTPStatus.OK,
            headers={"Cache-Control": "no-store"},
        )
    raise RakitError(
        code=ErrorCode.CONFIG_INVALID,
        message="Unsupported action result for HTTP translation.",
        status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
    )


async def _action_result_response_with_adapter(
    binding: ActionBinding,
    request: Request,
    result: ActionResult[Any],
    *,
    fallback_location: str,
) -> Response:
    if not isinstance(result, ActionAdvancedResponse):
        return _action_result_response(
            request,
            result,
            fallback_location=fallback_location,
        )
    adapter = binding.advanced_response_adapter
    if adapter is None:
        raise RakitError(
            code=ErrorCode.CONFIG_INVALID,
            message="Action advanced responses require a configured web response adapter.",
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
        )
    response = adapter(request, result)
    if isinstance(response, Response):
        return response
    if inspect.isawaitable(response):
        resolved = await response
        if isinstance(resolved, Response):
            return resolved
    raise RakitError(
        code=ErrorCode.CONFIG_INVALID,
        message="Action advanced response adapters must return a Starlette Response.",
        status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
    )


def _receipt_message(receipt: OperationReceipt) -> str | None:
    if receipt.payload is None:
        return None
    message = receipt.payload.get("message")
    return message if isinstance(message, str) else None


def _validated_receipt_location(location: str | None) -> str | None:
    if location is None:
        return None
    try:
        return ActionRedirect(location=location).location
    except ValueError:
        return None


def _action_result_receipt(
    result: ActionResult[Any],
    *,
    operation_id: str,
    fallback_location: str,
) -> OperationReceipt:
    if isinstance(result, ActionSuccess):
        payload = {"message": result.message} if result.message is not None else None
        return OperationReceipt(
            operation_id=operation_id,
            status="succeeded",
            result_kind="success",
            redirect_route=fallback_location,
            payload=payload,
        )
    if isinstance(result, ActionRedirect):
        payload = {"message": result.message} if result.message is not None else None
        return OperationReceipt(
            operation_id=operation_id,
            status="succeeded",
            result_kind="redirect",
            redirect_route=result.location,
            payload=payload,
        )
    if isinstance(result, ActionRefresh):
        payload: dict[str, object] = {"target": result.target}
        if result.message is not None:
            payload["message"] = result.message
        return OperationReceipt(
            operation_id=operation_id,
            status="succeeded",
            result_kind="refresh",
            redirect_route=fallback_location,
            payload=payload,
        )
    if isinstance(result, ActionRendered):
        return OperationReceipt(
            operation_id=operation_id,
            status="succeeded",
            result_kind="rendered",
            redirect_route=fallback_location,
        )
    if isinstance(result, ActionAdvancedResponse):
        return OperationReceipt(
            operation_id=operation_id,
            status="succeeded",
            result_kind="advanced",
            redirect_route=fallback_location,
        )
    return OperationReceipt(
        operation_id=operation_id,
        status="succeeded",
        result_kind="unreplayable",
        redirect_route=fallback_location,
    )


def _completed_action_response(
    request: Request,
    receipt: OperationReceipt | None,
    *,
    fallback_location: str,
) -> Response:
    if receipt is None:
        return _rejected_response(
            request,
            "Action already completed, but its original response cannot be replayed",
            409,
        )

    replay_location = _validated_receipt_location(receipt.redirect_route) or fallback_location
    message = _receipt_message(receipt)

    # Backward compatibility for receipts written before semantic result kinds
    # were stored.  Those receipts already recorded the safe owner location.
    if receipt.result_kind == "action":
        return _action_result_response(
            request,
            ActionSuccess(message="Action already completed"),
            fallback_location=replay_location,
        )
    if receipt.result_kind == "success":
        return _action_result_response(
            request,
            ActionSuccess(message=message),
            fallback_location=replay_location,
        )
    if receipt.result_kind == "redirect":
        location = _validated_receipt_location(receipt.redirect_route)
        if location is None:
            return _rejected_response(
                request,
                "Action already completed, but its original response cannot be replayed",
                409,
            )
        return _action_result_response(
            request,
            ActionRedirect(location=location, message=message),
            fallback_location=fallback_location,
        )
    if receipt.result_kind == "refresh":
        target = receipt.payload.get("target") if receipt.payload is not None else None
        if not isinstance(target, str) or not target:
            return _rejected_response(
                request,
                "Action already completed, but its original response cannot be replayed",
                409,
            )
        return _action_result_response(
            request,
            ActionRefresh(target=target, message=message),
            fallback_location=replay_location,
        )
    return _rejected_response(
        request,
        "Action already completed, but its original response cannot be replayed",
        409,
    )


def _rejected_response(request: Request, message: str, status_code: int) -> Response:
    safe_message = escape(message, quote=True)
    if request.headers.get("HX-Request") == "true":
        return Response(
            status_code=status_code,
            content=f"<div class='rakit-error' role='alert'>{safe_message}</div>",
            headers={"Cache-Control": "no-store", "HX-Retarget": "#rakit-action-root"},
        )
    return HTMLResponse(
        "<main class='mx-auto w-full max-w-7xl px-4 py-6 sm:px-6 lg:px-8'>"
        f"<section class='rakit-panel p-4'><p class='text-sm text-red-900'>{safe_message}</p>"
        "<a class='rakit-button rakit-button-secondary mt-4' href='javascript:history.back()'>"
        "Go back</a></section></main>",
        status_code=status_code,
        headers={"Cache-Control": "no-store"},
    )


def build_action_routes(binding: ActionBinding) -> list[Route]:
    """Materialize compiler-owned action routes as Starlette ``Route`` objects.

    One neutral ``RouteDefinition`` declaring GET + POST becomes one Starlette
    ``Route`` with both methods, the compiler's stable route name, and the
    compiler's exact path.  The web layer adds no independent URL grammar.
    """

    routes: list[Route] = []
    for route_definition, compiled_action in binding.routes:
        action = compiled_action.definition
        route_path = route_definition.path
        owner_path = _owner_path(route_definition)

        async def action_get(
            request: Request,
            action: ActionDefinition = action,
            compiled_action: CompiledActionDefinition = compiled_action,
            route_path: str = route_path,
            owner_path: str = owner_path,
        ) -> Response:
            identity = _identity(binding, request, action)
            authorization = await binding.authorize_action(request, compiled_action, identity)
            if authorization is None:
                return _rejected_response(request, "Forbidden", 403)
            record = None
            if action.scope is ActionScope.RECORD and identity is not None:
                assert binding.load_record is not None
                record = await binding.load_record(identity)
                if record is None:
                    return _rejected_response(request, "Resource was not found", 404)
            context = _action_context(
                binding,
                request,
                action,
                identity=identity,
                record=record,
                authorization=authorization,
            )
            decision = await resolve_availability(action, context)
            if decision.availability is ActionAvailability.HIDDEN:
                return _rejected_response(request, "Resource was not found", 404)
            typed_confirmation = action.needs_confirmation and action.input_schema is not None
            concurrency_token = None
            if (
                action.requires_concurrency
                and not typed_confirmation
                and record is not None
                and identity is not None
            ):
                assert binding.concurrency is not None
                assert binding.concurrency_resource_id is not None
                assert binding.record_version is not None
                concurrency_token = binding.concurrency.issue(
                    binding.concurrency_resource_id,
                    identity,
                    binding.record_version(record),
                )
            preview = None
            if action.needs_preview and not typed_confirmation:
                preview = await resolve_preview(action, context)
            confirmation_token = None
            if action.needs_confirmation and not typed_confirmation:
                confirmation_token = _issue_confirmation(
                    binding,
                    request,
                    action,
                    identity,
                    authorization,
                    _confirmation_input_fingerprint(None, None),
                )
            template_args = _template_args(
                binding,
                request,
                action,
                identity,
                decision,
                preview,
                submitted={},
                issues=(),
                concurrency_token=concurrency_token,
                confirmation_token=confirmation_token,
                route_path=route_path,
                owner_path=owner_path,
            )
            template = "actions/form.html" if action.needs_form else "actions/confirm.html"
            return binding.templates.TemplateResponse(
                request,
                template,
                template_args,
                headers={"Cache-Control": "no-store"},
            )

        async def action_post(
            request: Request,
            action: ActionDefinition = action,
            compiled_action: CompiledActionDefinition = compiled_action,
            route_path: str = route_path,
            owner_path: str = owner_path,
        ) -> Response:
            if not await binding.verify_csrf(request):
                return _rejected_response(request, "Invalid CSRF token", 403)
            identity = _identity(binding, request, action)
            authorization = await binding.authorize_action(request, compiled_action, identity)
            if authorization is None:
                return _rejected_response(request, "Forbidden", 403)
            record = None
            if action.scope is ActionScope.RECORD and identity is not None:
                assert binding.load_record is not None
                record = await binding.load_record(identity)
                if record is None:
                    return _rejected_response(request, "Resource was not found", 404)
            try:
                form = await request.form(max_files=0, max_fields=_MAX_ACTION_FIELDS)
            except Exception as exc:
                raise RakitError(
                    code=ErrorCode.VALIDATION_FAILED,
                    message="Invalid action form",
                    status_code=HTTPStatus.BAD_REQUEST,
                ) from exc
            items = form.multi_items()
            names = [name for name, _ in items]
            if len(names) != len(set(names)):
                return _rejected_response(request, "Invalid action form", 400)
            reserved = {"csrf_token", "submission_token", "concurrency_token", "confirmation_token"}
            submitted = {
                name: value
                for name, value in items
                if isinstance(name, str) and isinstance(value, str) and name not in reserved
            }
            tokens = {
                name: value for name, value in items if name in reserved and isinstance(value, str)
            }
            state = None
            if action.input_schema is not None:
                try:
                    state = action.input_schema.parse(submitted)
                except FormValidationError as exc:
                    return await _validation_response(
                        binding,
                        request,
                        action,
                        identity,
                        record,
                        authorization,
                        submitted,
                        exc.state.issues,
                        route_path,
                        owner_path,
                    )
                except ValueError:
                    return _rejected_response(request, "Invalid action input", 400)
            elif submitted:
                return _rejected_response(request, "Invalid action input", 400)

            input_fingerprint = _confirmation_input_fingerprint(action.input_schema, state)
            typed_confirmation = action.needs_confirmation and action.input_schema is not None
            if typed_confirmation and not tokens.get("confirmation_token"):
                submission_token = tokens.get("submission_token")
                if not submission_token or not await binding.verify_submission_token(request):
                    return _rejected_response(request, "Invalid submission token", 409)
                typed_context = _action_context(
                    binding,
                    request,
                    action,
                    identity=identity,
                    record=record,
                    authorization=authorization,
                    submitted=submitted,
                    values=state,
                )
                decision = await resolve_availability(action, typed_context)
                if decision.availability is not ActionAvailability.AVAILABLE:
                    return _rejected_response(request, "This action is no longer available", 409)
                preview = await resolve_preview(action, typed_context)
                confirmation_token = _issue_confirmation(
                    binding,
                    request,
                    action,
                    identity,
                    authorization,
                    input_fingerprint,
                )
                concurrency_token = None
                if action.requires_concurrency and identity is not None and record is not None:
                    assert binding.concurrency is not None
                    assert binding.concurrency_resource_id is not None
                    assert binding.record_version is not None
                    concurrency_token = binding.concurrency.issue(
                        binding.concurrency_resource_id,
                        identity,
                        binding.record_version(record),
                    )
                template_args = _template_args(
                    binding,
                    request,
                    action,
                    identity,
                    decision,
                    preview,
                    submitted=submitted,
                    issues=(),
                    concurrency_token=concurrency_token,
                    confirmation_token=confirmation_token,
                    route_path=route_path,
                    owner_path=owner_path,
                )
                template = (
                    "actions/_confirm.html"
                    if request.headers.get("HX-Request") == "true"
                    else "actions/confirm.html"
                )
                headers = {"Cache-Control": "no-store"}
                if request.headers.get("HX-Request") == "true":
                    headers["HX-Retarget"] = "#rakit-action-root"
                return binding.templates.TemplateResponse(
                    request,
                    template,
                    template_args,
                    headers=headers,
                )

            if action.needs_confirmation and not _verify_confirmation(
                binding,
                request,
                action,
                identity,
                authorization,
                input_fingerprint,
                tokens.get("confirmation_token"),
            ):
                return _rejected_response(request, "Action confirmation is invalid or stale", 409)

            fallback_location = _owner_location(binding, request, identity, owner_path)
            reservation = None
            fingerprint = _action_fingerprint(action.action_id, identity, submitted)
            if binding.idempotency_store is not None:
                submission_token = tokens.get("submission_token")
                if not submission_token or not await binding.verify_submission_token(request):
                    return _rejected_response(request, "Invalid submission token", 409)
                try:
                    reservation = await binding.idempotency_store.begin(
                        hashlib.sha256(submission_token.encode()).hexdigest(),
                        fingerprint=fingerprint,
                    )
                except ValueError:
                    return _rejected_response(
                        request, "Submission token is bound to another action", 409
                    )
                if reservation.status is IdempotencyStatus.COMPLETED:
                    return _completed_action_response(
                        request,
                        reservation.completed_receipt,
                        fallback_location=fallback_location,
                    )
                if reservation.status is IdempotencyStatus.FAILED_FINAL:
                    return _rejected_response(
                        request,
                        "This submission has already failed and cannot be retried",
                        409,
                    )
                if not reservation.claimed:
                    return _rejected_response(request, "Action is already in progress", 409)

            async def release() -> None:
                if reservation is not None:
                    assert binding.idempotency_store is not None
                    await binding.idempotency_store.release(reservation)

            async def fail_final() -> None:
                if reservation is not None:
                    assert binding.idempotency_store is not None
                    await _fail_final_reservation(binding.idempotency_store, reservation)

            context = _action_context(
                binding,
                request,
                action,
                identity=identity,
                record=record,
                authorization=authorization,
                submitted=submitted,
                values=state,
                confirmation_token=tokens.get("confirmation_token"),
            )
            decision = await resolve_availability(action, context)
            if decision.availability is not ActionAvailability.AVAILABLE:
                await release()
                return _rejected_response(request, "This action is no longer available", 409)

            if action.requires_concurrency and identity is not None and record is not None:
                assert binding.concurrency is not None
                assert binding.concurrency_resource_id is not None
                assert binding.record_version is not None
                token = tokens.get("concurrency_token")
                try:
                    binding.concurrency.verify(
                        token or "",
                        binding.concurrency_resource_id,
                        identity,
                        binding.record_version(record),
                    )
                except (RakitError, ValueError):
                    await release()
                    return _rejected_response(
                        request, "The resource has changed since this action was opened", 409
                    )

            context = _action_context(
                binding,
                request,
                action,
                identity=identity,
                record=record,
                authorization=authorization,
                submitted=submitted,
                values=state,
                concurrency_token=tokens.get("concurrency_token"),
                confirmation_token=tokens.get("confirmation_token"),
            )

            def rakit_error_response(exc: RakitError) -> Response:
                status_code = exc.status_code or 400
                message = exc.message or "Action rejected"
                if status_code == HTTPStatus.CONFLICT:
                    message = "This action is no longer available"
                return _rejected_response(request, message, status_code)

            try:
                plan = build_action_operation_plan(context, idempotency_fingerprint=fingerprint)
            except RakitError as exc:
                await release()
                return rakit_error_response(exc)
            except BaseException:
                await release()
                raise

            try:
                result = await _run_action_operation(binding, request, plan, authorization)
            except RakitError as exc:
                await fail_final()
                return rakit_error_response(exc)
            except BaseException:
                await fail_final()
                raise
            if isinstance(result, ActionValidation):
                if reservation is not None:
                    assert binding.idempotency_store is not None
                    await binding.idempotency_store.release(reservation)
                return await _validation_response(
                    binding,
                    request,
                    action,
                    identity,
                    record,
                    authorization,
                    submitted,
                    result.issues,
                    route_path,
                    owner_path,
                )
            if isinstance(result, ActionRejected):
                if reservation is not None:
                    assert binding.idempotency_store is not None
                    await binding.idempotency_store.release(reservation)
                return _action_result_response(
                    request,
                    result,
                    fallback_location=fallback_location,
                )
            try:
                response = await _action_result_response_with_adapter(
                    binding,
                    request,
                    result,
                    fallback_location=fallback_location,
                )
            except BaseException:
                await fail_final()
                raise
            if reservation is not None:
                assert binding.idempotency_store is not None
                await binding.idempotency_store.complete(
                    reservation,
                    _action_result_receipt(
                        result,
                        operation_id=str(reservation.reservation_id),
                        fallback_location=fallback_location,
                    ),
                )
            return response

        async def action_endpoint(
            request: Request,
            action: ActionDefinition = action,
            compiled_action: CompiledActionDefinition = compiled_action,
            action_get: Callable[..., Awaitable[Response]] = action_get,
            action_post: Callable[..., Awaitable[Response]] = action_post,
        ) -> Response:
            if request.method == "POST":
                return await action_post(request, action=action, compiled_action=compiled_action)
            return await action_get(request, action=action, compiled_action=compiled_action)

        routes.append(
            Route(
                route_path,
                action_endpoint,
                methods=["GET", "POST"],
                name=route_definition.route_name,
            )
        )
    return routes


def _issue_confirmation(
    binding: ActionBinding,
    request: Request,
    action: ActionDefinition,
    identity: RecordIdentity | None,
    authorization: OperationAuthorization,
    input_fingerprint: str,
) -> str:
    assert binding.token_service is not None
    return binding.token_service.issue_in(
        "action_confirmation",
        _confirmation_claims(
            request,
            action,
            identity,
            authorization,
            input_fingerprint,
        ),
        _CONFIRMATION_TTL,
    )


def _verify_confirmation(
    binding: ActionBinding,
    request: Request,
    action: ActionDefinition,
    identity: RecordIdentity | None,
    authorization: OperationAuthorization,
    input_fingerprint: str,
    token: str | None,
) -> bool:
    if not token:
        return False
    assert binding.token_service is not None
    try:
        claims = binding.token_service.verify(token, expected_purpose="action_confirmation")
    except ValueError:
        return False
    return claims == _confirmation_claims(
        request,
        action,
        identity,
        authorization,
        input_fingerprint,
    )


def _template_args(
    binding: ActionBinding,
    request: Request,
    action: ActionDefinition,
    identity: RecordIdentity | None,
    availability: ActionAvailabilityDecision,
    preview: Any,
    *,
    submitted: Mapping[str, object],
    issues: tuple[FormIssue, ...],
    concurrency_token: str | None,
    confirmation_token: str | None,
    route_path: str,
    owner_path: str,
) -> dict[str, object]:
    confirmation_fields = tuple(
        {
            "name": field.field_id,
            "value": submitted[field.field_id],
        }
        for field in (action.input_schema.fields if action.input_schema is not None else ())
        if (
            field.writable
            and field.readable
            and not field.sensitive
            and field.field_id in submitted
        )
    )
    return {
        "action": action,
        "binding_label": binding.label,
        "availability": availability,
        "fields": _field_views(action.input_schema, submitted, issues),
        "issues": issues,
        "csrf_token": request.cookies.get(CSRF_COOKIE_NAME, ""),
        "submission_token": binding.issue_submission_token(request),
        "concurrency_token": concurrency_token or "",
        "confirmation_token": confirmation_token or "",
        "confirmation_fields": confirmation_fields,
        "form_action": mounted_path(request, _with_identity(binding, identity, route_path)),
        "cancel_url": _owner_location(binding, request, identity, owner_path),
        "preview": preview,
    }


async def _validation_response(
    binding: ActionBinding,
    request: Request,
    action: ActionDefinition,
    identity: RecordIdentity | None,
    record: object | None,
    authorization: OperationAuthorization,
    submitted: Mapping[str, object],
    issues: tuple[FormIssue, ...],
    route_path: str,
    owner_path: str,
) -> Response:
    context = _action_context(
        binding,
        request,
        action,
        identity=identity,
        record=record,
        authorization=authorization,
        submitted=submitted,
    )
    decision = await resolve_availability(action, context)
    concurrency_token = None
    if action.requires_concurrency and record is not None and identity is not None:
        assert binding.concurrency is not None
        assert binding.concurrency_resource_id is not None
        assert binding.record_version is not None
        concurrency_token = binding.concurrency.issue(
            binding.concurrency_resource_id,
            identity,
            binding.record_version(record),
        )
    template_args = _template_args(
        binding,
        request,
        action,
        identity,
        decision,
        None,
        submitted=submitted,
        issues=issues,
        concurrency_token=concurrency_token,
        confirmation_token="",
        route_path=route_path,
        owner_path=owner_path,
    )
    if request.headers.get("HX-Request") == "true":
        return binding.templates.TemplateResponse(
            request,
            "actions/_form.html",
            template_args,
            status_code=HTTPStatus.UNPROCESSABLE_ENTITY,
            headers={"Cache-Control": "no-store", "HX-Retarget": "#rakit-action-root"},
        )
    return binding.templates.TemplateResponse(
        request,
        "actions/form.html",
        template_args,
        status_code=HTTPStatus.UNPROCESSABLE_ENTITY,
        headers={"Cache-Control": "no-store"},
    )


def _owner_location(
    binding: ActionBinding,
    request: Request,
    identity: RecordIdentity | None,
    owner_path: str,
) -> str:
    return mounted_path(request, _with_identity(binding, identity, owner_path))


__all__ = [
    "ActionBinding",
    "AdvancedActionResponseAdapter",
    "build_action_routes",
]
