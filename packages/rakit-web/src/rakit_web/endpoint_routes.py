"""Starlette runtime for compiler-owned custom endpoints."""
from http import HTTPStatus

import hashlib
import json
from collections.abc import AsyncIterable, Awaitable, Callable, Iterable, Mapping
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from typing import Any

import anyio
from rakit_core.auth import Principal
from rakit_core.definitions import CompiledEndpointDefinition, RouteDefinition
from rakit_core.di import ServiceResolver
from rakit_core.endpoints import (
    EndpointAccessPolicy,
    EndpointContext,
    EndpointExecutionResult,
    EndpointFileResult,
    EndpointInputSource,
    EndpointMethod,
    EndpointResponseKind,
    EndpointResult,
    EndpointStreamResult,
    build_endpoint_operation_plan,
)
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
    OperationExecutorCapabilities,
    OperationPlan,
    activate_operation_context,
    new_operation_id,
    resolve_operation_executor_capabilities,
    run_operation_plan,
    run_with_deadline,
)
from rakit_core.permissions import PermissionRequirement
from rakit_core.schema import SchemaAdapter, SchemaValidationError
from rakit_core.transactions import OperationUnitOfWorkFactory, TransactionPolicy
from starlette.exceptions import HTTPException
from starlette.requests import Request
from starlette.responses import JSONResponse, Response, StreamingResponse
from starlette.routing import Route

_MAX_ENDPOINT_FIELDS = 500
_MAX_ENDPOINT_PART_SIZE = 1024 * 1024
_MAX_IDEMPOTENCY_KEY_LENGTH = 256
_PUBLIC_PERMISSION_PREFIX = "__rakit.public_endpoint__"


@dataclass(frozen=True)
class EndpointBinding:
    """Concrete web dependencies for compiler-owned endpoint routes."""

    routes: tuple[tuple[RouteDefinition, CompiledEndpointDefinition], ...]
    admin_id: str
    superuser_bypass: bool
    schema_adapter: SchemaAdapter
    verify_csrf: Callable[[Request], Awaitable[bool]] | None = None
    idempotency_store: IdempotencyStore | None = None
    deadline_seconds: float | None = None
    operation_scope: Callable[[], AbstractAsyncContextManager[ServiceResolver]] | None = None
    unit_of_work_factory: Callable[[], OperationUnitOfWorkFactory | None] | None = None

    def __post_init__(self) -> None:
        for route, compiled in self.routes:
            endpoint = compiled.definition
            if route.path != endpoint.path:
                raise ValueError("Compiled endpoint route path must match EndpointDefinition.path")
            if route.methods != tuple(method.value for method in endpoint.methods):
                raise ValueError(
                    "Compiled endpoint route methods must match EndpointDefinition.methods"
                )
            if EndpointMethod.POST in endpoint.methods and (
                self.verify_csrf is None or self.idempotency_store is None
            ):
                raise ValueError("POST endpoints require CSRF and idempotency support")


def _error_response(
    code: ErrorCode | str,
    message: str,
    status_code: int,
    *,
    details: object | None = None,
) -> JSONResponse:
    error: dict[str, object] = {"code": str(code), "message": message}
    if details is not None:
        error["details"] = details
    return JSONResponse(
        {"error": error},
        status_code=status_code,
        headers={"Cache-Control": "no-store"},
    )


def _rakit_error_response(exc: RakitError) -> JSONResponse:
    return _error_response(exc.code, exc.message, exc.status_code, details=exc.details or None)


def _validation_response(
    message: str,
    *,
    issues: list[dict[str, object]],
    status_code: int = 422,
) -> JSONResponse:
    return _error_response(
        ErrorCode.VALIDATION_FAILED,
        message,
        status_code,
        details={"issues": issues},
    )


def _issue(location: str, code: str, message: str) -> dict[str, object]:
    return {"location": [location], "code": code, "message": message}


def _schema_issues(exc: SchemaValidationError) -> list[dict[str, object]]:
    return [
        {
            "location": list(issue.location),
            "code": issue.code,
            "message": issue.message,
        }
        for issue in exc.issues
    ]


def _unknown_issues(
    schema_adapter: SchemaAdapter,
    schema: type[object] | None,
    submitted: Mapping[str, object],
) -> list[dict[str, object]]:
    known = set(schema_adapter.field_names(schema)) if schema is not None else set()
    return [
        _issue(name, "unknown_field", "Unknown endpoint input field")
        for name in submitted
        if name not in known
    ]


def _validate_values(
    schema_adapter: SchemaAdapter,
    schema: type[object] | None,
    submitted: Mapping[str, object],
) -> tuple[object | None, list[dict[str, object]]]:
    unknown = _unknown_issues(schema_adapter, schema, submitted)
    if unknown:
        return None, unknown
    if schema is None:
        return None, []
    try:
        return schema_adapter.validate_input(schema, submitted), []
    except SchemaValidationError as exc:
        return None, _schema_issues(exc)


def _query_input(request: Request) -> tuple[dict[str, object], list[dict[str, object]]]:
    items = list(request.query_params.multi_items())
    names = [name for name, _ in items]
    duplicates = sorted({name for name in names if names.count(name) > 1})
    if duplicates:
        return {}, [
            _issue(name, "duplicate_field", "Duplicate query parameters are not allowed")
            for name in duplicates
        ]
    return {name: value for name, value in items}, []


class _DuplicateJsonKey(ValueError):
    def __init__(self, key: str) -> None:
        super().__init__(key)
        self.key = key


def _json_object_pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise _DuplicateJsonKey(key)
        result[key] = value
    return result


async def _json_input(request: Request) -> tuple[dict[str, object], list[dict[str, object]]]:
    content_type = request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
    if content_type != "application/json" and not content_type.endswith("+json"):
        return {}, [_issue("__root__", "content_type", "Expected an application/json body")]
    try:
        raw = await request.body()
        payload = json.loads(raw.decode("utf-8"), object_pairs_hook=_json_object_pairs)
    except _DuplicateJsonKey as exc:
        return {}, [_issue(exc.key, "duplicate_field", "Duplicate JSON fields are not allowed")]
    except (UnicodeDecodeError, json.JSONDecodeError):
        return {}, [_issue("__root__", "invalid_json", "Malformed JSON body")]
    if not isinstance(payload, dict):
        return {}, [_issue("__root__", "object_required", "JSON body must be an object")]
    return payload, []


async def _form_input(request: Request) -> tuple[dict[str, object], list[dict[str, object]]]:
    try:
        form = await request.form(
            max_files=0,
            max_fields=_MAX_ENDPOINT_FIELDS,
            max_part_size=_MAX_ENDPOINT_PART_SIZE,
        )
    except (HTTPException, ValueError, TypeError):
        return {}, [_issue("__root__", "invalid_form", "Invalid endpoint form body")]
    items = list(form.multi_items())
    names = [str(name) for name, _ in items]
    duplicates = sorted({name for name in names if names.count(name) > 1})
    if duplicates:
        return {}, [
            _issue(name, "duplicate_field", "Duplicate form fields are not allowed")
            for name in duplicates
        ]
    non_strings = [str(name) for name, value in items if not isinstance(value, str)]
    if non_strings:
        return {}, [
            _issue(name, "file_not_supported", "File uploads are not supported by custom endpoints")
            for name in non_strings
        ]
    return {str(name): value for name, value in items}, []


async def _submitted_input(
    request: Request,
    compiled: CompiledEndpointDefinition,
) -> tuple[dict[str, object], list[dict[str, object]]]:
    endpoint = compiled.definition
    source = endpoint.input_source
    if source is EndpointInputSource.QUERY:
        return _query_input(request)
    if source is EndpointInputSource.JSON:
        return await _json_input(request)
    if source is EndpointInputSource.FORM:
        return await _form_input(request)
    if source is not None:
        return {}, [_issue("__root__", "input_source", "Unsupported endpoint input source")]

    # No schema means no unchecked free-form bag. Empty request input is fine;
    # unexpected query/body data is rejected explicitly.
    if request.query_params:
        return {}, [_issue("__root__", "unexpected_input", "Endpoint does not accept query input")]
    if request.method == "POST":
        body = await request.body()
        if body.strip() not in (b"", b"{}"):
            return {}, [
                _issue("__root__", "unexpected_input", "Endpoint does not accept body input")
            ]
    return {}, []


def _request_state(request: Request) -> Mapping[str, object]:
    state = request.scope.get("state", {})
    return state if isinstance(state, Mapping) else {}


def _principal(request: Request) -> Principal | None:
    principal = _request_state(request).get("principal")
    return principal if isinstance(principal, Principal) else None


def _endpoint_access(
    binding: EndpointBinding,
    request: Request,
    compiled: CompiledEndpointDefinition,
) -> tuple[OperationAuthorization | None, PermissionRequirement | None, JSONResponse | None]:
    endpoint = compiled.definition
    principal = _principal(request)
    operation = f"endpoint:{endpoint.endpoint_id}"

    if endpoint.access_policy is EndpointAccessPolicy.PUBLIC:
        # A synthetic requirement is an internal capability identity, not an
        # RBAC permission. execute_operation_plan checks exact capability
        # binding but never re-runs PermissionRequirement.matches().
        requirement = PermissionRequirement.all_of(
            f"{_PUBLIC_PERMISSION_PREFIX}.{endpoint.endpoint_id}"
        )
        principal_id = (
            principal.subject_id
            if principal is not None
            and principal.authenticated
            and principal.subject_id is not None
            else "anonymous"
        )
        return (
            OperationAuthorization.for_requirement(
                admin_id=binding.admin_id,
                resource_id=str(endpoint.endpoint_id),
                operation=operation,
                principal_id=principal_id,
                requirement=requirement,
            ),
            requirement,
            None,
        )

    if principal is None or not principal.authenticated or principal.subject_id is None:
        return (
            None,
            None,
            _error_response(
                ErrorCode.AUTH_UNAUTHENTICATED,
                "Authentication is required.",
                401,
            ),
        )
    if not compiled.permission.matches(principal, superuser_bypass=binding.superuser_bypass):
        return (
            None,
            None,
            _error_response(
                ErrorCode.AUTH_FORBIDDEN,
                "You are not allowed to invoke this endpoint.",
                403,
            ),
        )
    return (
        OperationAuthorization.for_requirement(
            admin_id=binding.admin_id,
            resource_id=str(endpoint.endpoint_id),
            operation=operation,
            principal_id=principal.subject_id,
            requirement=compiled.permission,
        ),
        compiled.permission,
        None,
    )


class _ValidatedEndpointHandler:
    """Validate semantic result/output while still inside the operation/UoW."""

    def __init__(self, compiled: CompiledEndpointDefinition, schema_adapter: SchemaAdapter) -> None:
        self.compiled = compiled
        self.schema_adapter = schema_adapter
        handler = compiled.definition.handler
        if handler is None or not callable(handler):
            raise ValueError("Compiled endpoint requires a callable handler")
        self.handler = handler
        self.capabilities: OperationExecutorCapabilities = resolve_operation_executor_capabilities(
            handler
        )

    async def __call__(self, context: EndpointContext) -> EndpointExecutionResult[Any]:
        result = self.handler(context)
        if isinstance(result, Awaitable):
            result = await result
        endpoint = self.compiled.definition
        if endpoint.response_kind is EndpointResponseKind.JSON:
            if not isinstance(result, EndpointResult):
                raise RakitError(
                    code=ErrorCode.CONFIG_INVALID,
                    message="JSON endpoint handler returned an incompatible result type.",
                    status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
                    details={
                        "endpoint_id": str(endpoint.endpoint_id),
                        "reason": "result_kind_mismatch",
                    },
                )
            payload: object = result.payload
            if endpoint.output_schema is not None:
                try:
                    payload = self.schema_adapter.serialize_output(endpoint.output_schema, payload)
                except SchemaValidationError as exc:
                    raise RakitError(
                        code=ErrorCode.VALIDATION_FAILED,
                        message="Endpoint output validation failed.",
                        status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
                        details={"issues": _schema_issues(exc)},
                    ) from exc
            return EndpointResult(payload=payload, status_code=result.status_code)
        if endpoint.response_kind is EndpointResponseKind.FILE and isinstance(
            result, EndpointFileResult
        ):
            return result
        if endpoint.response_kind is EndpointResponseKind.STREAM and isinstance(
            result, EndpointStreamResult
        ):
            return result
        raise RakitError(
            code=ErrorCode.CONFIG_INVALID,
            message="Endpoint handler returned a result that does not match its response kind.",
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            details={"endpoint_id": str(endpoint.endpoint_id), "reason": "result_kind_mismatch"},
        )


def _endpoint_fingerprint(
    endpoint_id: str,
    schema_adapter: SchemaAdapter,
    schema: type[object] | None,
    values: object | None,
) -> str:
    input_value: object = (
        schema_adapter.serialize_output(schema, values)
        if schema is not None and values is not None
        else {}
    )
    encoded = json.dumps(
        {"endpoint_id": endpoint_id, "input": input_value},
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _idempotency_token_hash(
    binding: EndpointBinding,
    request: Request,
    compiled: CompiledEndpointDefinition,
    authorization: OperationAuthorization,
) -> tuple[str | None, JSONResponse | None]:
    values = request.headers.getlist("idempotency-key")
    if len(values) != 1:
        return None, _error_response(
            ErrorCode.VALIDATION_FAILED,
            "POST endpoints require exactly one Idempotency-Key header.",
            400,
        )
    key = values[0]
    if not key or key.strip() != key or len(key) > _MAX_IDEMPOTENCY_KEY_LENGTH:
        return None, _error_response(
            ErrorCode.VALIDATION_FAILED,
            "Idempotency-Key is invalid.",
            400,
        )
    session_id = str(_request_state(request).get("session_id", ""))
    scope = "\x1f".join(
        (
            binding.admin_id,
            str(compiled.definition.endpoint_id),
            authorization.principal_id,
            session_id,
            key,
        )
    )
    return hashlib.sha256(scope.encode("utf-8")).hexdigest(), None


async def _fail_final(store: IdempotencyStore, reservation: IdempotencyReservation) -> None:
    with anyio.CancelScope(shield=True):
        await store.fail_final(reservation)


def _completed_response(receipt: OperationReceipt | None) -> JSONResponse:
    if receipt is None or receipt.result_kind != "endpoint_json" or receipt.payload is None:
        return _error_response(
            ErrorCode.RESOURCE_CONFLICT,
            "Endpoint submission already completed, but its response cannot be replayed.",
            409,
        )
    status_code = receipt.payload.get("status_code")
    if (
        not isinstance(status_code, int)
        or not 200 <= status_code < HTTPStatus.MULTIPLE_CHOICES
        or "payload" not in receipt.payload
    ):
        return _error_response(
            ErrorCode.RESOURCE_CONFLICT,
            "Endpoint submission already completed, but its response cannot be replayed.",
            409,
        )
    return JSONResponse(
        receipt.payload["payload"],
        status_code=status_code,
        headers={"Cache-Control": "no-store"},
    )


async def _run_endpoint_operation(
    binding: EndpointBinding,
    request: Request,
    plan: OperationPlan[EndpointContext, EndpointExecutionResult[Any]],
    authorization: OperationAuthorization,
    requirement: PermissionRequirement,
) -> EndpointExecutionResult[Any]:
    deadline = (
        Deadline.after(binding.deadline_seconds) if binding.deadline_seconds is not None else None
    )
    request_state = _request_state(request)
    services: ServiceResolver | None = None
    events: EventPublisher | None = None

    async def run_with_services() -> EndpointExecutionResult[Any]:
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
            permission_requirement=requirement,
            services=services,
            events=events,
        )
        with activate_operation_context(operation_context):
            operation_context.checkpoint()
            operation = run_operation_plan(
                plan,
                operation_context,
                unit_of_work_factory=uow_factory,
            )
            if deadline is None:
                return await operation
            return await run_with_deadline(operation, deadline)

    if binding.operation_scope is not None:
        async with binding.operation_scope() as operation_services:
            services = operation_services
            events = operation_services.require(EventPublisher)
            return await run_with_services()
    return await run_with_services()


def _result_response(result: EndpointExecutionResult[Any]) -> Response:
    if isinstance(result, EndpointResult):
        return JSONResponse(
            result.payload,
            status_code=result.status_code,
            headers={"Cache-Control": "no-store"},
        )
    if isinstance(result, EndpointFileResult):
        quoted = result.filename.replace('"', "")
        return Response(
            result.content,
            status_code=result.status_code,
            media_type=result.content_type,
            headers={
                "Cache-Control": "no-store",
                "Content-Disposition": f'attachment; filename="{quoted}"',
            },
        )
    if isinstance(result, EndpointStreamResult):
        stream: AsyncIterable[bytes] | Iterable[bytes] = result.stream
        return StreamingResponse(
            stream,
            status_code=result.status_code,
            media_type=result.content_type,
            headers={"Cache-Control": "no-store"},
        )
    raise AssertionError("unreachable endpoint result")


def build_endpoint_routes(binding: EndpointBinding) -> list[Route]:
    routes: list[Route] = []
    for route_definition, compiled_endpoint in binding.routes:

        async def endpoint_handler(
            request: Request,
            compiled_endpoint: CompiledEndpointDefinition = compiled_endpoint,
        ) -> Response:
            endpoint = compiled_endpoint.definition
            authorization, requirement, access_error = _endpoint_access(
                binding, request, compiled_endpoint
            )
            if access_error is not None:
                return access_error
            assert authorization is not None
            assert requirement is not None

            if request.method == "POST":
                assert binding.verify_csrf is not None
                if not await binding.verify_csrf(request):
                    return _error_response(
                        ErrorCode.AUTH_FORBIDDEN,
                        "CSRF validation failed.",
                        403,
                    )

            submitted, parse_issues = await _submitted_input(request, compiled_endpoint)
            if parse_issues:
                status_code = (
                    400
                    if any(
                        issue["code"] in {"invalid_json", "content_type", "invalid_form"}
                        for issue in parse_issues
                    )
                    else 422
                )
                return _validation_response(
                    "Endpoint input validation failed.",
                    issues=parse_issues,
                    status_code=status_code,
                )
            values, validation_issues = _validate_values(
                binding.schema_adapter, endpoint.input_schema, submitted
            )
            if validation_issues:
                return _validation_response(
                    "Endpoint input validation failed.",
                    issues=validation_issues,
                )

            context = EndpointContext(
                endpoint_id=str(endpoint.endpoint_id),
                values=values,
                authorization=authorization,
                principal=_principal(request),
            )
            handler = _ValidatedEndpointHandler(compiled_endpoint, binding.schema_adapter)
            fingerprint: str | None = None
            reservation: IdempotencyReservation | None = None

            if request.method == "POST":
                assert binding.idempotency_store is not None
                token_hash, token_error = _idempotency_token_hash(
                    binding, request, compiled_endpoint, authorization
                )
                if token_error is not None:
                    return token_error
                assert token_hash is not None
                fingerprint = _endpoint_fingerprint(
                    str(endpoint.endpoint_id),
                    binding.schema_adapter,
                    endpoint.input_schema,
                    values,
                )
                try:
                    reservation = await binding.idempotency_store.begin(
                        token_hash,
                        fingerprint=fingerprint,
                    )
                except ValueError:
                    return _error_response(
                        ErrorCode.RESOURCE_CONFLICT,
                        "Idempotency-Key is already bound to different endpoint input.",
                        409,
                    )
                if reservation.status is IdempotencyStatus.COMPLETED:
                    return _completed_response(reservation.completed_receipt)
                if reservation.status is IdempotencyStatus.FAILED_FINAL:
                    return _error_response(
                        ErrorCode.RESOURCE_CONFLICT,
                        "This endpoint submission has already failed and cannot be retried.",
                        409,
                    )
                if not reservation.claimed:
                    return _error_response(
                        ErrorCode.RESOURCE_CONFLICT,
                        "Endpoint submission is already in progress.",
                        409,
                    )

            try:
                plan = build_endpoint_operation_plan(
                    context,
                    handler=handler,
                    mutating=endpoint.mutating,
                    transaction_policy=endpoint.transaction_policy,
                    idempotency_fingerprint=fingerprint,
                )
                result = await _run_endpoint_operation(
                    binding,
                    request,
                    plan,
                    authorization,
                    requirement,
                )
            except RakitError as exc:
                if reservation is not None and binding.idempotency_store is not None:
                    await _fail_final(binding.idempotency_store, reservation)
                return _rakit_error_response(exc)
            except BaseException:
                if reservation is not None and binding.idempotency_store is not None:
                    await _fail_final(binding.idempotency_store, reservation)
                raise

            if reservation is not None:
                assert binding.idempotency_store is not None
                if not isinstance(result, EndpointResult):
                    await _fail_final(binding.idempotency_store, reservation)
                    return _error_response(
                        ErrorCode.CONFIG_INVALID,
                        "POST endpoint produced a non-replayable response.",
                        500,
                    )
                await binding.idempotency_store.complete(
                    reservation,
                    OperationReceipt(
                        operation_id=str(reservation.reservation_id),
                        status="succeeded",
                        result_kind="endpoint_json",
                        payload={
                            "status_code": result.status_code,
                            "payload": result.payload,
                        },
                    ),
                )
            return _result_response(result)

        routes.append(
            Route(
                route_definition.path,
                endpoint_handler,
                methods=list(route_definition.methods),
                name=route_definition.route_name,
            )
        )
    return routes


__all__ = ["EndpointBinding", "build_endpoint_routes"]
