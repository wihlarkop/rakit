"""Synchronous web runtime for Plan 05 Task 5 BULK actions.

Bulk actions reuse the Task 4 action permission, operation, transaction,
idempotency, CSRF, and submission-token seams. Selection is always decoded
and scoped-loaded server-side. ATOMIC runs all targets inside one root UoW;
BEST_EFFORT gives each target its own operation/UoW and reports a safe semantic
aggregate without persisting arbitrary action payloads.
"""

import hashlib
import json
from collections.abc import Awaitable, Callable, Mapping
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from datetime import timedelta

from rakit_core.actions import (
    ActionAvailability,
    ActionContext,
    ActionDefinition,
    ActionRedirect,
    ActionScope,
    resolve_availability,
)
from rakit_core.bulk import (
    BulkActionOutcome,
    BulkExecutionPolicy,
    BulkItemOutcome,
    BulkItemStatus,
    BulkSelection,
    BulkTarget,
)
from rakit_core.bulk_actions import (
    build_atomic_bulk_operation_plan,
    build_bulk_target_operation_plan,
    bulk_item_outcome,
)
from rakit_core.concurrency import ConcurrencyTokenService
from rakit_core.crypto import TokenService
from rakit_core.definitions import CompiledActionDefinition, RouteDefinition
from rakit_core.di import ServiceResolver
from rakit_core.errors import ErrorCode, RakitError
from rakit_core.events import EventPublisher
from rakit_core.forms import FormIssue, FormState, FormValidationError
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
from starlette.datastructures import FormData
from starlette.requests import Request
from starlette.responses import Response
from starlette.routing import Route
from starlette.templating import Jinja2Templates

from ._paths import mounted_path
from .action_routes import _fail_final_reservation, _field_views, _rejected_response
from .results import mutation_success
from .security.cookies import CSRF_COOKIE_NAME

_BULK_CONFIRMATION_TTL = timedelta(minutes=15)
_MAX_BULK_FIELDS = 500


@dataclass(frozen=True)
class BulkActionBinding:
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
    load_record: Callable[[RecordIdentity], Awaitable[object | None]]
    token_service: TokenService
    idempotency_store: IdempotencyStore
    concurrency: ConcurrencyTokenService | None = None
    concurrency_resource_id: str | None = None
    record_version: Callable[[object], object] | None = None
    deadline_seconds: float | None = None
    operation_scope: Callable[[], AbstractAsyncContextManager[ServiceResolver]] | None = None
    unit_of_work_factory: Callable[[], OperationUnitOfWorkFactory | None] | None = None
    label: str = "Bulk actions"

    def __post_init__(self) -> None:
        for route, compiled in self.routes:
            action = compiled.definition
            if action.scope is not ActionScope.BULK:
                raise ValueError("BulkActionBinding accepts only BULK actions")
            if route.methods != ("GET", "POST") or "{identity}" in route.path:
                raise ValueError("BULK action routes must be collection-level GET/POST routes")
            policy = action.bulk_policy
            if policy is None:
                raise ValueError("BULK actions require BulkPolicy")
            if policy.require_concurrency_snapshot and (
                self.concurrency is None
                or self.concurrency_resource_id is None
                or self.record_version is None
            ):
                raise ValueError(
                    f"Bulk action {action.action_id!r} requires a concurrency snapshot provider"
                )


def _owner_path(route: RouteDefinition) -> str:
    owner, separator, _ = route.path.rpartition("/_actions/")
    if not separator:
        raise ValueError("Bulk action route must live below /_actions/")
    return owner or "/"


def _session_id(request: Request) -> str:
    state = request.scope.get("state", {})
    if not isinstance(state, Mapping):
        return ""
    session_id = state.get("session_id")
    return session_id if isinstance(session_id, str) else ""


def _selection_fingerprint(
    action: ActionDefinition,
    selection: BulkSelection,
    codec: IdentityCodec,
    submitted: Mapping[str, object],
) -> str:
    payload = {
        "action_id": str(action.action_id),
        "selection": sorted(codec.encode(identity) for identity in selection.identities),
        "input": dict(sorted(submitted.items())),
    }
    encoded = json.dumps(payload, sort_keys=True, default=str, separators=(",", ":"))
    return hashlib.sha256(encoded.encode()).hexdigest()


def _confirmation_required(action: ActionDefinition, selected_count: int) -> bool:
    policy = action.bulk_policy
    assert policy is not None
    return action.needs_confirmation or selected_count >= policy.confirmation_threshold


def _confirmation_claims(
    request: Request,
    action: ActionDefinition,
    authorization: OperationAuthorization,
    selection: BulkSelection,
    codec: IdentityCodec,
) -> dict[str, object]:
    return {
        "admin_id": authorization.admin_id,
        "resource_id": action.resource_id,
        "action_id": action.action_id,
        "principal_id": authorization.principal_id,
        "session_id": _session_id(request),
        "selection": sorted(codec.encode(identity) for identity in selection.identities),
    }


def _issue_confirmation(
    binding: BulkActionBinding,
    request: Request,
    action: ActionDefinition,
    authorization: OperationAuthorization,
    selection: BulkSelection,
) -> str:
    return binding.token_service.issue_in(
        "bulk_action_confirmation",
        _confirmation_claims(request, action, authorization, selection, binding.codec),
        _BULK_CONFIRMATION_TTL,
    )


def _verify_confirmation(
    binding: BulkActionBinding,
    request: Request,
    action: ActionDefinition,
    authorization: OperationAuthorization,
    selection: BulkSelection,
    token: str,
) -> bool:
    try:
        claims = binding.token_service.verify(token, expected_purpose="bulk_action_confirmation")
    except ValueError:
        return False
    return claims == _confirmation_claims(
        request,
        action,
        authorization,
        selection,
        binding.codec,
    )


def _selection_tokens_from_query(request: Request) -> list[str]:
    return [value for value in request.query_params.getlist("selected") if value]


def _selection_tokens_from_form(form: FormData) -> list[str]:
    return [
        value
        for value in form.getlist("selected")
        if isinstance(value, str) and value
    ]


async def _resolve_selection(
    binding: BulkActionBinding,
    action: ActionDefinition,
    encoded: list[str],
) -> BulkSelection:
    policy = action.bulk_policy
    assert policy is not None
    if not encoded:
        raise RakitError(
            code=ErrorCode.VALIDATION_FAILED,
            message="Select at least one resource before running a bulk action.",
            status_code=400,
        )
    if len(encoded) > policy.synchronous_maximum:
        raise RakitError(
            code=ErrorCode.VALIDATION_FAILED,
            message="Bulk selection exceeds the synchronous execution limit.",
            status_code=400,
            details={"maximum": policy.synchronous_maximum},
        )

    identities: list[RecordIdentity] = []
    seen: set[str] = set()
    for token in encoded:
        try:
            identity = binding.codec.decode(token)
        except ValueError as exc:
            raise RakitError(
                code=ErrorCode.VALIDATION_FAILED,
                message="Bulk selection contains an invalid identity.",
                status_code=400,
            ) from exc
        key = binding.codec.encode(identity)
        if key in seen:
            continue
        seen.add(key)
        identities.append(identity)

    targets: list[BulkTarget] = []
    for identity in identities:
        record = await binding.load_record(identity)
        if record is None:
            raise RakitError(
                code=ErrorCode.RESOURCE_NOT_FOUND,
                message="A selected resource is no longer available.",
                status_code=404,
            )
        targets.append(BulkTarget(identity=identity, record=record))
    return BulkSelection(tuple(targets))


def _bulk_context(
    request: Request,
    action: ActionDefinition,
    target: BulkTarget,
    authorization: OperationAuthorization,
    *,
    submitted: Mapping[str, object],
    values: FormState | None,
) -> ActionContext:
    return ActionContext(
        definition=action,
        scope=ActionScope.BULK,
        identity=target.identity,
        record=target.record,
        submitted=submitted,
        values=values,
        authorization=authorization,
        principal=request.scope.get("state", {}).get("principal"),
    )


async def _target_contexts(
    binding: BulkActionBinding,
    request: Request,
    compiled: CompiledActionDefinition,
    selection: BulkSelection,
    *,
    submitted: Mapping[str, object],
    values: FormState | None,
) -> tuple[ActionContext, ...]:
    contexts: list[ActionContext] = []
    for target in selection.targets:
        authorization = await binding.authorize_action(request, compiled, target.identity)
        if authorization is None:
            raise RakitError(
                code=ErrorCode.AUTH_FORBIDDEN,
                message="Forbidden",
                status_code=403,
            )
        context = _bulk_context(
            request,
            compiled.definition,
            target,
            authorization,
            submitted=submitted,
            values=values,
        )
        decision = await resolve_availability(compiled.definition, context)
        if decision.availability is not ActionAvailability.AVAILABLE:
            raise RakitError(
                code=ErrorCode.RESOURCE_CONFLICT,
                message="A selected resource is no longer eligible for this action.",
                status_code=409,
            )
        contexts.append(context)
    return tuple(contexts)


def _concurrency_tokens(
    binding: BulkActionBinding,
    action: ActionDefinition,
    selection: BulkSelection,
) -> tuple[str, ...]:
    policy = action.bulk_policy
    assert policy is not None
    if not policy.require_concurrency_snapshot:
        return ()
    assert binding.concurrency is not None
    assert binding.concurrency_resource_id is not None
    assert binding.record_version is not None
    return tuple(
        binding.concurrency.issue(
            binding.concurrency_resource_id,
            target.identity,
            binding.record_version(target.record),
        )
        for target in selection.targets
    )


def _verify_concurrency_tokens(
    binding: BulkActionBinding,
    action: ActionDefinition,
    selection: BulkSelection,
    tokens: list[str],
) -> None:
    policy = action.bulk_policy
    assert policy is not None
    if not policy.require_concurrency_snapshot:
        return
    if len(tokens) != len(selection.targets):
        raise RakitError(
            code=ErrorCode.RESOURCE_CONFLICT,
            message="Bulk concurrency snapshot is missing or stale.",
            status_code=409,
        )
    assert binding.concurrency is not None
    assert binding.concurrency_resource_id is not None
    assert binding.record_version is not None
    try:
        for target, token in zip(selection.targets, tokens, strict=True):
            binding.concurrency.verify(
                token,
                binding.concurrency_resource_id,
                target.identity,
                binding.record_version(target.record),
            )
    except (RakitError, ValueError) as exc:
        raise RakitError(
            code=ErrorCode.RESOURCE_CONFLICT,
            message="A selected resource changed after the bulk action was opened.",
            status_code=409,
        ) from exc


def _parse_input(
    action: ActionDefinition,
    form: FormData,
) -> tuple[dict[str, object], FormState | None]:
    reserved = {
        "csrf_token",
        "submission_token",
        "confirmation_token",
        "concurrency_token",
        "selected",
    }
    items = list(form.multi_items())
    if len(items) > _MAX_BULK_FIELDS:
        raise RakitError(
            code=ErrorCode.VALIDATION_FAILED,
            message="Bulk action input has too many fields.",
            status_code=400,
        )
    submitted = {
        name: value
        for name, value in items
        if isinstance(name, str)
        and isinstance(value, str)
        and name not in reserved
    }
    if action.input_schema is None:
        if submitted:
            raise RakitError(
                code=ErrorCode.VALIDATION_FAILED,
                message="Invalid bulk action input.",
                status_code=400,
            )
        return submitted, None
    try:
        return submitted, action.input_schema.parse(submitted)
    except FormValidationError:
        raise
    except ValueError as exc:
        raise RakitError(
            code=ErrorCode.VALIDATION_FAILED,
            message="Invalid bulk action input.",
            status_code=400,
        ) from exc


async def _run_plan[TInput, TResult](
    binding: BulkActionBinding,
    request: Request,
    plan: OperationPlan[TInput, TResult],
    authorization: OperationAuthorization,
) -> TResult:
    deadline = (
        Deadline.after(binding.deadline_seconds)
        if binding.deadline_seconds is not None
        else None
    )
    request_state = request.scope.get("state", {})
    request_state = request_state if isinstance(request_state, Mapping) else {}
    session_id = request_state.get("session_id")
    session_id = session_id if isinstance(session_id, str) else ""
    services: ServiceResolver | None = None
    events: EventPublisher | None = None

    async def run() -> TResult:
        needs_uow = plan.mutating and plan.transaction_policy in (
            TransactionPolicy.AUTO,
            TransactionPolicy.MANUAL,
        )
        unit_of_work_factory = (
            binding.unit_of_work_factory()
            if needs_uow and binding.unit_of_work_factory is not None
            else None
        )
        operation_context = OperationContext(
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
        with activate_operation_context(operation_context):
            operation_context.checkpoint()
            operation = run_operation_plan(
                plan,
                operation_context,
                unit_of_work_factory=unit_of_work_factory,
            )
            if deadline is None:
                return await operation
            return await run_with_deadline(operation, deadline)

    if binding.operation_scope is None:
        return await run()
    async with binding.operation_scope() as operation_services:
        services = operation_services
        events = operation_services.require(EventPublisher)
        return await run()


def _receipt(
    reservation: IdempotencyReservation,
    outcome: BulkActionOutcome,
    *,
    fallback_location: str,
) -> OperationReceipt:
    return OperationReceipt(
        operation_id=str(reservation.reservation_id),
        status="succeeded",
        result_kind="bulk",
        redirect_route=fallback_location,
        payload={
            "selected": outcome.selected_count,
            "succeeded": outcome.succeeded_count,
            "rejected": outcome.rejected_count,
            "skipped": outcome.skipped_count,
        },
    )


def _validated_location(location: str | None) -> str | None:
    if location is None:
        return None
    try:
        return ActionRedirect(location=location).location
    except ValueError:
        return None


def _completed_response(
    request: Request,
    receipt: OperationReceipt | None,
    fallback: str,
) -> Response:
    if receipt is None or receipt.result_kind != "bulk":
        return _rejected_response(
            request,
            "Bulk action already completed, but its response cannot be replayed",
            409,
        )
    location = _validated_location(receipt.redirect_route)
    if location is None:
        return _rejected_response(
            request,
            "Bulk action already completed, but its response cannot be replayed",
            409,
        )
    payload = receipt.payload or {}
    succeeded = payload.get("succeeded")
    selected = payload.get("selected")
    message = (
        f"Bulk action already completed: {succeeded}/{selected} succeeded"
        if isinstance(succeeded, int) and isinstance(selected, int)
        else "Bulk action already completed"
    )
    return mutation_success(
        request,
        location=location,
        refresh_targets=("rakit:bulk-refresh",),
        message=message,
    )


def _outcome_response(
    request: Request,
    outcome: BulkActionOutcome,
    fallback: str,
) -> Response:
    message = (
        f"Bulk action completed: {outcome.succeeded_count}/"
        f"{outcome.selected_count} succeeded"
    )
    if outcome.execution is BulkExecutionPolicy.ATOMIC and not outcome.all_succeeded:
        first = next(
            (item for item in outcome.items if item.status is BulkItemStatus.REJECTED),
            None,
        )
        return _rejected_response(
            request,
            first.message
            if first is not None and first.message
            else "Bulk action was rejected",
            409,
        )
    if outcome.succeeded_count == 0:
        return _rejected_response(request, "No selected resources were changed", 409)
    return mutation_success(
        request,
        location=fallback,
        refresh_targets=("rakit:bulk-refresh",),
        message=message,
    )


def _form_args(
    binding: BulkActionBinding,
    request: Request,
    action: ActionDefinition,
    route_path: str,
    owner_path: str,
    selection: BulkSelection,
    encoded_selection: tuple[str, ...],
    concurrency_tokens: tuple[str, ...],
    confirmation_token: str,
    *,
    submitted: Mapping[str, object] = {},
    issues: tuple[FormIssue, ...] = (),
) -> dict[str, object]:
    return {
        "action": action,
        "binding_label": binding.label,
        "selected_count": len(selection.targets),
        "selected": encoded_selection,
        "concurrency_tokens": concurrency_tokens,
        "confirmation_required": _confirmation_required(action, len(selection.targets)),
        "confirmation_token": confirmation_token,
        "csrf_token": request.cookies.get(CSRF_COOKIE_NAME, ""),
        "submission_token": binding.issue_submission_token(request),
        "fields": _field_views(action.input_schema, submitted, issues),
        "issues": issues,
        "form_action": mounted_path(request, route_path),
        "cancel_url": mounted_path(request, owner_path),
    }


async def _render_bulk_form(
    binding: BulkActionBinding,
    request: Request,
    action: ActionDefinition,
    authorization: OperationAuthorization,
    route_path: str,
    owner_path: str,
    selection: BulkSelection,
    *,
    submitted: Mapping[str, object] = {},
    issues: tuple[FormIssue, ...] = (),
    status_code: int = 200,
) -> Response:
    encoded_selection = tuple(
        binding.codec.encode(identity) for identity in selection.identities
    )
    concurrency_tokens = _concurrency_tokens(binding, action, selection)
    confirmation_token = (
        _issue_confirmation(binding, request, action, authorization, selection)
        if _confirmation_required(action, len(selection.targets))
        else ""
    )
    return binding.templates.TemplateResponse(
        request,
        "actions/bulk.html",
        _form_args(
            binding,
            request,
            action,
            route_path,
            owner_path,
            selection,
            encoded_selection,
            concurrency_tokens,
            confirmation_token,
            submitted=submitted,
            issues=issues,
        ),
        status_code=status_code,
        headers={"Cache-Control": "no-store"},
    )


def build_bulk_action_routes(binding: BulkActionBinding) -> list[Route]:
    routes: list[Route] = []
    for route_definition, compiled in binding.routes:
        action = compiled.definition
        route_path = route_definition.path
        owner_path = _owner_path(route_definition)

        async def bulk_get(
            request: Request,
            action: ActionDefinition = action,
            compiled: CompiledActionDefinition = compiled,
            route_path: str = route_path,
            owner_path: str = owner_path,
        ) -> Response:
            root_authorization = await binding.authorize_action(request, compiled, None)
            if root_authorization is None:
                return _rejected_response(request, "Forbidden", 403)
            try:
                selection = await _resolve_selection(
                    binding,
                    action,
                    _selection_tokens_from_query(request),
                )
                await _target_contexts(
                    binding,
                    request,
                    compiled,
                    selection,
                    submitted={},
                    values=None,
                )
            except RakitError as exc:
                return _rejected_response(request, exc.message, exc.status_code)
            return await _render_bulk_form(
                binding,
                request,
                action,
                root_authorization,
                route_path,
                owner_path,
                selection,
            )

        async def bulk_post(
            request: Request,
            action: ActionDefinition = action,
            compiled: CompiledActionDefinition = compiled,
            route_path: str = route_path,
            owner_path: str = owner_path,
        ) -> Response:
            if not await binding.verify_csrf(request):
                return _rejected_response(request, "Invalid CSRF token", 403)
            form = await request.form()
            root_authorization = await binding.authorize_action(request, compiled, None)
            if root_authorization is None:
                return _rejected_response(request, "Forbidden", 403)

            try:
                selection = await _resolve_selection(
                    binding,
                    action,
                    _selection_tokens_from_form(form),
                )
                submitted, values = _parse_input(action, form)
            except FormValidationError as exc:
                try:
                    selection = await _resolve_selection(
                        binding,
                        action,
                        _selection_tokens_from_form(form),
                    )
                except RakitError as selection_error:
                    return _rejected_response(
                        request,
                        selection_error.message,
                        selection_error.status_code,
                    )
                submitted = {
                    key: value
                    for key, value in form.items()
                    if isinstance(key, str) and isinstance(value, str)
                }
                return await _render_bulk_form(
                    binding,
                    request,
                    action,
                    root_authorization,
                    route_path,
                    owner_path,
                    selection,
                    submitted=submitted,
                    issues=exc.state.issues,
                    status_code=422,
                )
            except RakitError as exc:
                return _rejected_response(request, exc.message, exc.status_code)

            if _confirmation_required(action, len(selection.targets)):
                token = form.get("confirmation_token")
                if not isinstance(token, str) or not _verify_confirmation(
                    binding,
                    request,
                    action,
                    root_authorization,
                    selection,
                    token,
                ):
                    return _rejected_response(
                        request,
                        "Bulk action confirmation is invalid or stale",
                        409,
                    )

            try:
                _verify_concurrency_tokens(
                    binding,
                    action,
                    selection,
                    [
                        value
                        for value in form.getlist("concurrency_token")
                        if isinstance(value, str)
                    ],
                )
                contexts = await _target_contexts(
                    binding,
                    request,
                    compiled,
                    selection,
                    submitted=submitted,
                    values=values,
                )
            except RakitError as exc:
                return _rejected_response(request, exc.message, exc.status_code)

            submission_token = form.get("submission_token")
            if not isinstance(submission_token, str) or not await binding.verify_submission_token(
                request
            ):
                return _rejected_response(request, "Invalid submission token", 409)
            fingerprint = _selection_fingerprint(
                action,
                selection,
                binding.codec,
                submitted,
            )
            try:
                reservation = await binding.idempotency_store.begin(
                    hashlib.sha256(submission_token.encode()).hexdigest(),
                    fingerprint=fingerprint,
                )
            except ValueError:
                return _rejected_response(
                    request,
                    "Submission token is bound to another bulk action",
                    409,
                )

            fallback = mounted_path(request, owner_path)
            if reservation.status is IdempotencyStatus.COMPLETED:
                return _completed_response(request, reservation.completed_receipt, fallback)
            if reservation.status is IdempotencyStatus.FAILED_FINAL:
                return _rejected_response(
                    request,
                    "This bulk submission already failed and cannot be retried",
                    409,
                )
            if not reservation.claimed:
                return _rejected_response(request, "Bulk action is already in progress", 409)

            async def release() -> None:
                await binding.idempotency_store.release(reservation)

            async def fail_final() -> None:
                await _fail_final_reservation(binding.idempotency_store, reservation)

            policy = action.bulk_policy
            assert policy is not None
            if policy.execution is BulkExecutionPolicy.ATOMIC:
                try:
                    plan = build_atomic_bulk_operation_plan(
                        contexts,
                        authorization=root_authorization,
                        idempotency_fingerprint=fingerprint,
                    )
                except (RakitError, ValueError) as exc:
                    await release()
                    message = exc.message if isinstance(exc, RakitError) else str(exc)
                    return _rejected_response(request, message, 500)
                try:
                    outcome = await _run_plan(
                        binding,
                        request,
                        plan,
                        root_authorization,
                    )
                except RakitError as exc:
                    await fail_final()
                    return _rejected_response(request, exc.message, exc.status_code)
                except BaseException:
                    await fail_final()
                    raise
                if not outcome.all_succeeded:
                    await release()
                    return _outcome_response(request, outcome, fallback)
            else:
                items: list[BulkItemOutcome] = []
                for context in contexts:
                    assert context.authorization is not None
                    try:
                        plan = build_bulk_target_operation_plan(
                            context,
                            idempotency_fingerprint=fingerprint,
                        )
                    except (RakitError, ValueError) as exc:
                        await fail_final()
                        message = exc.message if isinstance(exc, RakitError) else str(exc)
                        return _rejected_response(request, message, 500)
                    try:
                        result = await _run_plan(
                            binding,
                            request,
                            plan,
                            context.authorization,
                        )
                        items.append(bulk_item_outcome(context, result))
                    except RakitError as exc:
                        await fail_final()
                        return _rejected_response(request, exc.message, exc.status_code)
                    except BaseException:
                        await fail_final()
                        raise
                outcome = BulkActionOutcome(
                    execution=BulkExecutionPolicy.BEST_EFFORT,
                    items=tuple(items),
                )
                if outcome.succeeded_count == 0:
                    await release()
                    return _outcome_response(request, outcome, fallback)

            await binding.idempotency_store.complete(
                reservation,
                _receipt(
                    reservation,
                    outcome,
                    fallback_location=fallback,
                ),
            )
            return _outcome_response(request, outcome, fallback)

        async def endpoint(
            request: Request,
            get: Callable[..., Awaitable[Response]] = bulk_get,
            post: Callable[..., Awaitable[Response]] = bulk_post,
        ) -> Response:
            return await post(request) if request.method == "POST" else await get(request)

        routes.append(
            Route(
                route_path,
                endpoint,
                methods=["GET", "POST"],
                name=route_definition.route_name,
            )
        )
    return routes


__all__ = ["BulkActionBinding", "build_bulk_action_routes"]
