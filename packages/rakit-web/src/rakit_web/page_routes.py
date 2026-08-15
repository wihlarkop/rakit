"""Web runtime for compiled Plan 05 Task 6 custom pages."""

import hashlib
import json
from collections.abc import Awaitable, Callable, Mapping
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from html import escape
from typing import Any

import anyio
from pydantic import BaseModel, ValidationError
from rakit_core.auth import Principal
from rakit_core.definitions import CompiledPageDefinition, RouteDefinition
from rakit_core.di import ServiceResolver
from rakit_core.errors import ErrorCode, RakitError
from rakit_core.events import EventPublisher
from rakit_core.idempotency import (
    IdempotencyReservation,
    IdempotencyStatus,
    IdempotencyStore,
    OperationReceipt,
)
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
from rakit_core.pages import (
    PageContext,
    PageExecutionResult,
    PageRedirect,
    PageRejected,
    PageResult,
    build_page_operation_plan,
)
from rakit_core.transactions import OperationUnitOfWorkFactory, TransactionPolicy
from starlette.requests import Request
from starlette.responses import HTMLResponse, RedirectResponse, Response
from starlette.routing import Route
from starlette.templating import Jinja2Templates

from ._paths import mounted_path
from .security.cookies import CSRF_COOKIE_NAME

_MAX_PAGE_FIELDS = 500
_RESERVED_FORM_FIELDS = frozenset({"csrf_token", "submission_token"})


@dataclass(frozen=True)
class PageBinding:
    """Concrete web adapters for compiler-owned Page routes."""

    routes: tuple[tuple[RouteDefinition, CompiledPageDefinition], ...]
    templates: Jinja2Templates
    authorize_page: Callable[
        [Request, CompiledPageDefinition], Awaitable[OperationAuthorization | None]
    ]
    verify_csrf: Callable[[Request], Awaitable[bool]] | None = None
    verify_submission_token: Callable[[Request], Awaitable[bool]] | None = None
    issue_submission_token: Callable[[Request], str] | None = None
    idempotency_store: IdempotencyStore | None = None
    deadline_seconds: float | None = None
    operation_scope: Callable[[], AbstractAsyncContextManager[ServiceResolver]] | None = None
    unit_of_work_factory: Callable[[], OperationUnitOfWorkFactory | None] | None = None
    label: str = "Pages"

    def __post_init__(self) -> None:
        for route, compiled in self.routes:
            page = compiled.definition
            expected_methods = ("GET", "POST") if page.mutating else ("GET",)
            if route.methods != expected_methods:
                raise ValueError(
                    f"Page route {route.route_name!r} must declare {expected_methods!r}"
                )
            if route.path != page.path:
                raise ValueError("Compiled page route path must match PageDefinition.path")
            if page.mutating and (
                self.verify_csrf is None
                or self.verify_submission_token is None
                or self.issue_submission_token is None
                or self.idempotency_store is None
            ):
                raise ValueError("Mutating pages require CSRF, submission, and idempotency support")


def _page_fingerprint(page_id: str, submitted: Mapping[str, object]) -> str:
    encoded = json.dumps(
        {"page_id": page_id, "input": dict(sorted(submitted.items()))},
        sort_keys=True,
        default=str,
        separators=(",", ":"),
    )
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _request_state(request: Request) -> Mapping[str, object]:
    state = request.scope.get("state", {})
    return state if isinstance(state, Mapping) else {}


def _principal(request: Request) -> Principal | None:
    principal = _request_state(request).get("principal")
    return principal if isinstance(principal, Principal) else None


def _field_views(
    schema: type[BaseModel] | None,
    submitted: Mapping[str, object],
    issues: Mapping[str, tuple[str, ...]],
) -> tuple[dict[str, object], ...]:
    if schema is None:
        return ()
    views: list[dict[str, object]] = []
    for name, field in schema.model_fields.items():
        views.append(
            {
                "id": f"rakit-page-{name}",
                "name": name,
                "label": field.title or name.replace("_", " ").title(),
                "description": field.description,
                "value": submitted.get(name, ""),
                "issues": issues.get(name, ()),
            }
        )
    return tuple(views)


def _validation_issues(exc: ValidationError) -> dict[str, tuple[str, ...]]:
    issues: dict[str, tuple[str, ...]] = {}
    for error in exc.errors(include_url=False, include_context=False, include_input=False):
        location = error.get("loc", ())
        field = str(location[0]) if location else "__root__"
        message = str(error.get("msg", "Invalid value"))
        issues[field] = (*issues.get(field, ()), message)
    return issues


def _template_args(
    binding: PageBinding,
    request: Request,
    compiled: CompiledPageDefinition,
    *,
    result: PageResult[Any] | None = None,
    submitted: Mapping[str, object] | None = None,
    issues: Mapping[str, tuple[str, ...]] | None = None,
    message: str | None = None,
) -> dict[str, object]:
    page = compiled.definition
    safe_submitted = submitted or {}
    safe_issues = issues or {}
    return {
        "binding_label": binding.label,
        "page": page,
        "payload": result.payload if result is not None else None,
        "message": message if message is not None else (result.message if result is not None else None),
        "fields": _field_views(page.input_schema, safe_submitted, safe_issues),
        "issues": safe_issues,
        "form_action": mounted_path(request, page.path),
        "csrf_token": request.cookies.get(CSRF_COOKIE_NAME, ""),
        "submission_token": (
            binding.issue_submission_token(request)
            if page.mutating and binding.issue_submission_token is not None
            else ""
        ),
    }


def _render_page(
    binding: PageBinding,
    request: Request,
    compiled: CompiledPageDefinition,
    *,
    result: PageResult[Any] | None = None,
    submitted: Mapping[str, object] | None = None,
    issues: Mapping[str, tuple[str, ...]] | None = None,
    message: str | None = None,
    status_code: int | None = None,
) -> Response:
    page = compiled.definition
    return binding.templates.TemplateResponse(
        request,
        page.template,
        _template_args(
            binding,
            request,
            compiled,
            result=result,
            submitted=submitted,
            issues=issues,
            message=message,
        ),
        status_code=status_code or (result.status_code if result is not None else 200),
        headers={"Cache-Control": "no-store"},
    )


def _rejected_response(message: str, status_code: int) -> Response:
    safe = escape(message, quote=True)
    return HTMLResponse(
        "<main class='mx-auto w-full max-w-7xl px-4 py-6 sm:px-6 lg:px-8'>"
        f"<section class='rakit-panel p-4'><p class='text-sm text-red-900'>{safe}</p>"
        "</section></main>",
        status_code=status_code,
        headers={"Cache-Control": "no-store"},
    )


def _result_response(
    binding: PageBinding,
    request: Request,
    compiled: CompiledPageDefinition,
    result: PageExecutionResult[Any],
    *,
    submitted: Mapping[str, object] | None = None,
) -> Response:
    if isinstance(result, PageResult):
        return _render_page(binding, request, compiled, result=result, submitted=submitted)
    if isinstance(result, PageRedirect):
        return RedirectResponse(
            mounted_path(request, result.location),
            status_code=303,
            headers={"Cache-Control": "no-store"},
        )
    if isinstance(result, PageRejected):
        return _render_page(
            binding,
            request,
            compiled,
            submitted=submitted,
            issues={name: (message,) for name, message in result.errors.items()},
            message=result.message,
            status_code=result.status_code,
        )
    raise RakitError(
        code=ErrorCode.CONFIG_INVALID,
        message="Unsupported page result for HTTP translation.",
        status_code=500,
    )


def _validated_redirect(location: str | None) -> str | None:
    if location is None:
        return None
    try:
        return PageRedirect(location).location
    except ValueError:
        return None


def _completed_response(request: Request, receipt: OperationReceipt | None) -> Response:
    if receipt is None or receipt.result_kind != "page_redirect":
        return _rejected_response(
            "Page submission already completed, but its response cannot be replayed", 409
        )
    location = _validated_redirect(receipt.redirect_route)
    if location is None:
        return _rejected_response(
            "Page submission already completed, but its response cannot be replayed", 409
        )
    return RedirectResponse(
        mounted_path(request, location),
        status_code=303,
        headers={"Cache-Control": "no-store"},
    )


async def _fail_final(store: IdempotencyStore, reservation: IdempotencyReservation) -> None:
    with anyio.CancelScope(shield=True):
        await store.fail_final(reservation)


async def _run_page_operation(
    binding: PageBinding,
    request: Request,
    plan: OperationPlan[PageContext, PageExecutionResult[Any]],
    authorization: OperationAuthorization,
) -> PageExecutionResult[Any]:
    deadline = (
        Deadline.after(binding.deadline_seconds) if binding.deadline_seconds is not None else None
    )
    request_state = _request_state(request)
    services: ServiceResolver | None = None
    events: EventPublisher | None = None

    async def run_with_services() -> PageExecutionResult[Any]:
        needs_uow = plan.mutating and plan.transaction_policy in (
            TransactionPolicy.AUTO,
            TransactionPolicy.MANUAL,
        )
        uow_factory = (
            binding.unit_of_work_factory()
            if needs_uow and binding.unit_of_work_factory is not None
            else None
        )
        operation_context = OperationContext(
            deadline=deadline,
            cancellation=CancellationContext(),
            request_id=str(request_state.get("request_id", "")),
            operation_id=new_operation_id(),
            principal=_principal(request),
            principal_id=authorization.principal_id,
            session_id=str(request_state.get("session_id", "")),
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
            operation = run_operation_plan(plan, operation_context, unit_of_work_factory=uow_factory)
            if deadline is None:
                return await operation
            return await run_with_deadline(operation, deadline)

    if binding.operation_scope is not None:
        async with binding.operation_scope() as operation_services:
            services = operation_services
            events = operation_services.require(EventPublisher)
            return await run_with_services()
    return await run_with_services()


def _model_values(schema: type[BaseModel] | None, submitted: Mapping[str, object]) -> BaseModel | None:
    if schema is None:
        if submitted:
            raise ValueError("Page does not accept input")
        return None
    return schema.model_validate(dict(submitted))


def _query_input(request: Request) -> tuple[dict[str, object], dict[str, tuple[str, ...]]]:
    items = list(request.query_params.multi_items())
    names = [name for name, _ in items]
    if len(names) != len(set(names)):
        return {}, {"__root__": ("Duplicate query parameters are not allowed",)}
    return {name: value for name, value in items}, {}


async def _form_input(
    request: Request,
) -> tuple[dict[str, object], dict[str, str], dict[str, tuple[str, ...]]]:
    try:
        form = await request.form(max_files=0, max_fields=_MAX_PAGE_FIELDS)
    except Exception as exc:
        raise RakitError(
            code=ErrorCode.VALIDATION_FAILED,
            message="Invalid page form",
            status_code=400,
        ) from exc
    items = list(form.multi_items())
    names = [str(name) for name, _ in items]
    if len(names) != len(set(names)):
        return {}, {}, {"__root__": ("Duplicate form fields are not allowed",)}
    submitted = {
        str(name): value
        for name, value in items
        if isinstance(value, str) and str(name) not in _RESERVED_FORM_FIELDS
    }
    tokens = {
        str(name): value
        for name, value in items
        if str(name) in _RESERVED_FORM_FIELDS and isinstance(value, str)
    }
    return submitted, tokens, {}


def build_page_routes(binding: PageBinding) -> list[Route]:
    routes: list[Route] = []
    for route_definition, compiled_page in binding.routes:

        async def page_get(
            request: Request,
            compiled_page: CompiledPageDefinition = compiled_page,
        ) -> Response:
            page = compiled_page.definition
            authorization = await binding.authorize_page(request, compiled_page)
            if authorization is None:
                return _rejected_response("Forbidden", 403)
            if page.mutating:
                # GET is presentation-only. Application mutation code is never
                # invoked until POST passes CSRF, typed parsing, and idempotency.
                return _render_page(binding, request, compiled_page)

            submitted, pre_issues = _query_input(request)
            if pre_issues:
                return _render_page(
                    binding,
                    request,
                    compiled_page,
                    submitted=submitted,
                    issues=pre_issues,
                    status_code=422,
                )
            try:
                values = _model_values(page.input_schema, submitted)
            except ValidationError as exc:
                return _render_page(
                    binding,
                    request,
                    compiled_page,
                    submitted=submitted,
                    issues=_validation_issues(exc),
                    status_code=422,
                )
            except ValueError:
                return _rejected_response("This page does not accept query input", 400)

            if page.handler is None:
                return _render_page(binding, request, compiled_page, result=PageResult())
            context = PageContext(
                definition=page,
                values=values,
                authorization=authorization,
                principal=_principal(request),
            )
            try:
                plan = build_page_operation_plan(context)
                result = await _run_page_operation(binding, request, plan, authorization)
            except RakitError as exc:
                return _rejected_response(exc.message, exc.status_code)
            return _result_response(binding, request, compiled_page, result, submitted=submitted)

        async def page_post(
            request: Request,
            compiled_page: CompiledPageDefinition = compiled_page,
        ) -> Response:
            page = compiled_page.definition
            if not page.mutating:
                return Response(status_code=405, headers={"Allow": "GET"})
            assert binding.verify_csrf is not None
            assert binding.verify_submission_token is not None
            assert binding.idempotency_store is not None
            if not await binding.verify_csrf(request):
                return _rejected_response("Invalid CSRF token", 403)
            authorization = await binding.authorize_page(request, compiled_page)
            if authorization is None:
                return _rejected_response("Forbidden", 403)

            submitted, tokens, pre_issues = await _form_input(request)
            if pre_issues:
                return _render_page(
                    binding,
                    request,
                    compiled_page,
                    submitted=submitted,
                    issues=pre_issues,
                    status_code=422,
                )
            try:
                values = _model_values(page.input_schema, submitted)
            except ValidationError as exc:
                return _render_page(
                    binding,
                    request,
                    compiled_page,
                    submitted=submitted,
                    issues=_validation_issues(exc),
                    status_code=422,
                )
            except ValueError:
                return _rejected_response("This page does not accept form input", 400)

            submission_token = tokens.get("submission_token")
            if not submission_token or not await binding.verify_submission_token(request):
                return _rejected_response("Invalid submission token", 409)
            fingerprint = _page_fingerprint(str(page.page_id), submitted)
            try:
                reservation = await binding.idempotency_store.begin(
                    hashlib.sha256(submission_token.encode()).hexdigest(),
                    fingerprint=fingerprint,
                )
            except ValueError:
                return _rejected_response("Submission token is bound to another page request", 409)
            if reservation.status is IdempotencyStatus.COMPLETED:
                return _completed_response(request, reservation.completed_receipt)
            if reservation.status is IdempotencyStatus.FAILED_FINAL:
                return _rejected_response(
                    "This submission has already failed and cannot be retried", 409
                )
            if not reservation.claimed:
                return _rejected_response("Page submission is already in progress", 409)

            async def release() -> None:
                await binding.idempotency_store.release(reservation)

            context = PageContext(
                definition=page,
                values=values,
                authorization=authorization,
                principal=_principal(request),
            )
            try:
                plan = build_page_operation_plan(context, idempotency_fingerprint=fingerprint)
            except BaseException:
                await release()
                raise

            try:
                result = await _run_page_operation(binding, request, plan, authorization)
            except RakitError as exc:
                await _fail_final(binding.idempotency_store, reservation)
                return _rejected_response(exc.message, exc.status_code)
            except BaseException:
                await _fail_final(binding.idempotency_store, reservation)
                raise

            if isinstance(result, PageRejected):
                await release()
                return _result_response(
                    binding,
                    request,
                    compiled_page,
                    result,
                    submitted=submitted,
                )
            if not isinstance(result, PageRedirect):
                await _fail_final(binding.idempotency_store, reservation)
                raise RakitError(
                    code=ErrorCode.CONFIG_INVALID,
                    message="Mutating page handlers must return PageRedirect.",
                    status_code=500,
                    details={"page_id": str(page.page_id), "reason": "post_redirect_required"},
                )

            response = _result_response(
                binding,
                request,
                compiled_page,
                result,
                submitted=submitted,
            )
            await binding.idempotency_store.complete(
                reservation,
                OperationReceipt(
                    operation_id=str(reservation.reservation_id),
                    status="succeeded",
                    result_kind="page_redirect",
                    redirect_route=result.location,
                ),
            )
            return response

        async def page_endpoint(
            request: Request,
            page_get: Callable[[Request], Awaitable[Response]] = page_get,
            page_post: Callable[[Request], Awaitable[Response]] = page_post,
        ) -> Response:
            if request.method == "POST":
                return await page_post(request)
            return await page_get(request)

        routes.append(
            Route(
                route_definition.path,
                page_endpoint,
                methods=list(route_definition.methods),
                name=route_definition.route_name,
            )
        )
    return routes


__all__ = ["PageBinding", "build_page_routes"]
