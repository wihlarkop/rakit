import hashlib
import json
import logging
from collections.abc import AsyncIterator, Awaitable, Callable, Mapping
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from uuid import UUID

from rakit_core.auth import Principal
from rakit_core.concurrency import ConcurrencyTokenService, ConcurrencyVersionProvider
from rakit_core.definitions import ResourceDefinition
from rakit_core.di import ServiceResolver
from rakit_core.errors import ErrorCode, RakitError
from rakit_core.events import EventPublisher
from rakit_core.generated_api import CompiledResourceApi, GeneratedCrudOperation
from rakit_core.generated_operations import (
    GeneratedCrudRequest,
    GeneratedMutationResult,
    GeneratedResourceExecutor,
    build_generated_operation_plan,
)
from rakit_core.idempotency import (
    IdempotencyReservation,
    IdempotencyStatus,
    IdempotencyStore,
    OperationReceipt,
)
from rakit_core.identity import IdentityCodec, RecordIdentity, canonical_identity_payload
from rakit_core.mutations import OperationAuthorization
from rakit_core.operations import (
    CancellationContext,
    Deadline,
    OperationContext,
    OperationExecutorCapabilities,
    activate_operation_context,
    new_operation_id,
    run_operation_plan,
)
from rakit_core.permissions import PermissionRequirement
from rakit_core.query import PageResult
from rakit_core.resources import ResourceService
from rakit_core.schema import SchemaAdapter
from rakit_core.transactions import OperationUnitOfWorkFactory
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from ._paths import mounted_path
from .generated_rest import (
    generated_error_payload,
    parse_generated_rest_query,
    serialize_generated_record,
    validate_generated_rest_payload,
)

_PUBLIC_READ_ACTOR = "rakit:public-read"
_LOGGER = logging.getLogger(__name__)
_MAX_JSON_BODY_BYTES = 1024 * 1024
_MAX_IDEMPOTENCY_KEY_LENGTH = 256


def _request_id(request: Request) -> str:
    value = request.scope.get("state", {}).get("request_id", "")
    return value if isinstance(value, str) else ""


def generated_error_response(request: Request, error: RakitError) -> JSONResponse:
    return JSONResponse(
        generated_error_payload(error, request_id=_request_id(request)),
        status_code=error.status_code,
        headers={"Cache-Control": "no-store"},
    )


def _unexpected_error_response(request: Request) -> JSONResponse:
    _LOGGER.exception(
        "Generated REST request failed unexpectedly",
        extra={"request_id": _request_id(request)},
    )
    return generated_error_response(
        request,
        RakitError(
            code=ErrorCode.INTERNAL_ERROR,
            message="Internal server error.",
            status_code=500,
        ),
    )


@dataclass(frozen=True, slots=True)
class GeneratedRestBinding:
    api: CompiledResourceApi
    definition: ResourceDefinition
    service: ResourceService
    schema_adapter: SchemaAdapter
    admin_id: str
    auth_enabled: bool
    superuser_bypass: bool = True
    codec: IdentityCodec = field(default_factory=IdentityCodec)
    generated_executor: GeneratedResourceExecutor | None = None
    verify_csrf: Callable[[Request], Awaitable[bool]] | None = None
    unit_of_work_factory: OperationUnitOfWorkFactory | None = None
    idempotency_store: IdempotencyStore | None = None
    operation_scope: Callable[[], AbstractAsyncContextManager[ServiceResolver]] | None = None
    concurrency_provider: ConcurrencyVersionProvider | None = None
    concurrency_tokens: ConcurrencyTokenService | None = None
    mutation_deadline_seconds: float = 30.0


class GeneratedReadExecutor:
    capabilities = OperationExecutorCapabilities()

    def __init__(self, service: ResourceService) -> None:
        self._service = service

    async def execute(self, context: OperationContext, request: GeneratedCrudRequest) -> object:
        context.checkpoint()
        if request.operation is GeneratedCrudOperation.LIST:
            assert request.query is not None
            return await self._service.list(request.query)
        if request.operation is GeneratedCrudOperation.DETAIL:
            assert request.identity is not None
            return await self._service.detail(request.identity)
        raise RakitError(
            code=ErrorCode.CONFIG_INVALID,
            message="Generated read executor received an unsupported operation.",
            status_code=500,
        )


def _principal(request: Request) -> Principal | None:
    value = request.scope.get("state", {}).get("principal")
    return value if isinstance(value, Principal) else None


def _permission_requirement(
    binding: GeneratedRestBinding, permission: str
) -> PermissionRequirement:
    return PermissionRequirement.all_of(
        f"{binding.admin_id}.resources.{binding.api.resource_id}.{permission}"
    )


def _read_requirement(binding: GeneratedRestBinding) -> PermissionRequirement:
    return _permission_requirement(binding, "read")


def _authorize_read(
    binding: GeneratedRestBinding,
    request: Request,
    *,
    operation: str,
    identity: RecordIdentity | None = None,
) -> OperationAuthorization:
    requirement = _read_requirement(binding)
    principal = _principal(request)
    if binding.auth_enabled:
        if principal is None or not principal.authenticated or principal.subject_id is None:
            raise RakitError(
                code=ErrorCode.AUTH_UNAUTHENTICATED,
                message="Authentication is required.",
                status_code=401,
            )
        if not requirement.matches(principal, superuser_bypass=binding.superuser_bypass):
            raise RakitError(
                code=ErrorCode.AUTH_FORBIDDEN,
                message="Permission denied.",
                status_code=403,
            )
        principal_id = principal.subject_id
    else:
        principal_id = _PUBLIC_READ_ACTOR

    return OperationAuthorization.for_requirement(
        admin_id=binding.admin_id,
        resource_id=binding.api.resource_id,
        operation=operation,
        principal_id=principal_id,
        requirement=requirement,
        target_identity=identity,
    )


def _authorize_mutation(
    binding: GeneratedRestBinding,
    request: Request,
    *,
    operation: str,
    identity: RecordIdentity | None,
) -> OperationAuthorization:
    if not binding.auth_enabled:
        raise RakitError(
            code=ErrorCode.CONFIG_INVALID,
            message="Generated CRUD mutation requires authentication.",
            status_code=500,
            details={
                "resource_id": binding.api.resource_id,
                "reason": "generated_api_auth_required",
            },
        )
    principal = _principal(request)
    if principal is None or not principal.authenticated or principal.subject_id is None:
        raise RakitError(
            code=ErrorCode.AUTH_UNAUTHENTICATED,
            message="Authentication is required.",
            status_code=401,
        )
    requirement = _permission_requirement(binding, operation)
    if not requirement.matches(principal, superuser_bypass=binding.superuser_bypass):
        raise RakitError(
            code=ErrorCode.AUTH_FORBIDDEN,
            message="Permission denied.",
            status_code=403,
        )
    return OperationAuthorization.for_requirement(
        admin_id=binding.admin_id,
        resource_id=binding.api.resource_id,
        operation=operation,
        principal_id=principal.subject_id,
        requirement=requirement,
        target_identity=identity,
    )


@asynccontextmanager
async def _operation_services(
    binding: GeneratedRestBinding,
) -> AsyncIterator[ServiceResolver | None]:
    if binding.operation_scope is None:
        yield None
    else:
        async with binding.operation_scope() as services:
            yield services


def _operation_context(
    binding: GeneratedRestBinding,
    request: Request,
    authorization: OperationAuthorization,
    services: ServiceResolver | None,
    *,
    deadline: Deadline | None = None,
) -> OperationContext:
    state = request.scope.get("state", {})
    session_id = state.get("session_id", "")
    return OperationContext(
        deadline=deadline,
        cancellation=CancellationContext(),
        request_id=_request_id(request),
        operation_id=new_operation_id(),
        principal=_principal(request),
        principal_id=authorization.principal_id,
        session_id=session_id if isinstance(session_id, str) else "",
        admin_id=authorization.admin_id,
        resource_id=authorization.resource_id,
        operation=authorization.operation,
        permissions=authorization.permissions,
        permission_requirement=authorization.requirement,
        services=services,
        events=services.require(EventPublisher) if services is not None else None,
    )


async def _run_read(
    binding: GeneratedRestBinding,
    request: Request,
    generated_request: GeneratedCrudRequest,
    authorization: OperationAuthorization,
) -> object:
    executor: GeneratedResourceExecutor = GeneratedReadExecutor(binding.service)
    plan = build_generated_operation_plan(binding.api, generated_request, authorization, executor)
    context = _operation_context(binding, request, authorization, None)
    with activate_operation_context(context):
        return await run_operation_plan(plan, context, unit_of_work_factory=None)


async def _run_mutation(
    binding: GeneratedRestBinding,
    request: Request,
    generated_request: GeneratedCrudRequest,
    authorization: OperationAuthorization,
    *,
    idempotency_fingerprint: str,
    reservation: IdempotencyReservation,
) -> tuple[object, str]:
    executor = binding.generated_executor
    if executor is None or binding.unit_of_work_factory is None:
        raise RakitError(
            code=ErrorCode.CONFIG_INVALID,
            message="Generated CRUD runtime is incomplete.",
            status_code=500,
            details={
                "resource_id": binding.api.resource_id,
                "reason": "generated_api_mutation_runtime_incomplete",
            },
        )
    concurrency_required = (
        binding.concurrency_provider is not None
        and generated_request.operation
        in {GeneratedCrudOperation.UPDATE_PARTIAL, GeneratedCrudOperation.DELETE}
    )
    plan = build_generated_operation_plan(
        binding.api,
        generated_request,
        authorization,
        executor,
        concurrency_required=concurrency_required,
        idempotency_fingerprint=idempotency_fingerprint,
    )
    async with _operation_services(binding) as services:
        context = _operation_context(
            binding,
            request,
            authorization,
            services,
            deadline=Deadline.after(binding.mutation_deadline_seconds),
        )
        try:
            with activate_operation_context(context):
                result = await run_operation_plan(
                    plan,
                    context,
                    unit_of_work_factory=binding.unit_of_work_factory,
                )
        except Exception:
            if not context.durable_commit_completed and binding.idempotency_store is not None:
                try:
                    await binding.idempotency_store.release(reservation)
                except Exception:
                    _LOGGER.exception(
                        "Failed to release pre-commit idempotency reservation",
                        extra={"request_id": context.request_id},
                    )
            raise
        return result, context.operation_id


def _list_response(binding: GeneratedRestBinding, result: object) -> JSONResponse:
    if not isinstance(result, PageResult):
        raise RakitError(
            code=ErrorCode.INTERNAL_ERROR,
            message="Generated list executor returned an invalid result.",
            status_code=500,
        )
    return JSONResponse(
        {
            "data": [
                serialize_generated_record(
                    binding.api,
                    item,
                    schema_adapter=binding.schema_adapter,
                )
                for item in result.items
            ],
            "meta": {
                "page": result.page,
                "per_page": result.per_page,
                "has_previous": result.has_previous,
                "has_next": result.has_next,
                "total": result.total_count,
            },
        },
        headers={"Cache-Control": "no-store"},
    )


def _etag_headers(
    binding: GeneratedRestBinding,
    identity: RecordIdentity,
    record: object,
) -> dict[str, str]:
    provider = binding.concurrency_provider
    tokens = binding.concurrency_tokens
    if provider is None and tokens is None:
        return {}
    if provider is None or tokens is None:
        raise RakitError(
            code=ErrorCode.CONFIG_INVALID,
            message="Generated CRUD concurrency runtime is incomplete.",
            status_code=500,
            details={
                "resource_id": binding.api.resource_id,
                "reason": "generated_api_concurrency_runtime_incomplete",
            },
        )
    token = tokens.issue(
        binding.api.resource_id,
        identity,
        provider.version_for(record),
        base_snapshot=provider.predicate_values_for(record),
    )
    return {"ETag": f'"{token}"'}


def _detail_response(
    binding: GeneratedRestBinding,
    identity: RecordIdentity,
    result: object,
) -> JSONResponse:
    headers = {"Cache-Control": "no-store"}
    headers.update(_etag_headers(binding, identity, result))
    return JSONResponse(
        {
            "data": serialize_generated_record(
                binding.api,
                result,
                schema_adapter=binding.schema_adapter,
            )
        },
        headers=headers,
    )


def _decode_identity(binding: GeneratedRestBinding, request: Request) -> RecordIdentity:
    raw_identity = request.path_params.get("identity")
    if not isinstance(raw_identity, str):
        raise RakitError(
            code=ErrorCode.VALIDATION_FAILED,
            message="Generated API identity is required.",
            status_code=400,
            details={"reason": "generated_api_identity_required"},
        )
    try:
        return binding.codec.decode(raw_identity)
    except ValueError as exc:
        raise RakitError(
            code=ErrorCode.VALIDATION_FAILED,
            message="Generated API identity is invalid.",
            status_code=400,
            details={"reason": "generated_api_identity_invalid"},
        ) from exc


def _if_match_token(binding: GeneratedRestBinding, request: Request) -> str | None:
    if binding.concurrency_provider is None:
        return None
    if binding.concurrency_tokens is None:
        raise RakitError(
            code=ErrorCode.CONFIG_INVALID,
            message="Generated CRUD concurrency token service is missing.",
            status_code=500,
            details={
                "resource_id": binding.api.resource_id,
                "reason": "generated_api_concurrency_runtime_incomplete",
            },
        )
    raw = request.headers.get("if-match")
    if raw is None:
        raise RakitError(
            code=ErrorCode.VALIDATION_FAILED,
            message="If-Match is required for this resource.",
            status_code=428,
            details={
                "resource_id": binding.api.resource_id,
                "reason": "generated_api_if_match_required",
            },
        )
    value = raw.strip()
    if (
        not value
        or value.startswith("W/")
        or "," in value
        or len(value) < 3
        or value[0] != '"'
        or value[-1] != '"'
        or '"' in value[1:-1]
    ):
        raise RakitError(
            code=ErrorCode.VALIDATION_FAILED,
            message="If-Match must contain exactly one strong ETag.",
            status_code=400,
            details={
                "resource_id": binding.api.resource_id,
                "reason": "generated_api_if_match_invalid",
            },
        )
    token = value[1:-1]
    if not token:
        raise RakitError(
            code=ErrorCode.VALIDATION_FAILED,
            message="If-Match must contain exactly one strong ETag.",
            status_code=400,
            details={
                "resource_id": binding.api.resource_id,
                "reason": "generated_api_if_match_invalid",
            },
        )
    return token


async def _verify_mutation_csrf(binding: GeneratedRestBinding, request: Request) -> None:
    verifier = binding.verify_csrf
    if verifier is None or not await verifier(request):
        raise RakitError(
            code=ErrorCode.AUTH_FORBIDDEN,
            message="Invalid CSRF token.",
            status_code=403,
        )


def _idempotency_key(binding: GeneratedRestBinding, request: Request) -> str:
    raw = request.headers.get("idempotency-key")
    if raw is None or not raw.strip() or len(raw) > _MAX_IDEMPOTENCY_KEY_LENGTH:
        raise RakitError(
            code=ErrorCode.VALIDATION_FAILED,
            message="Idempotency-Key is required.",
            status_code=400,
            details={
                "resource_id": binding.api.resource_id,
                "reason": "generated_api_idempotency_key_required",
            },
        )
    return raw.strip()


async def _json_payload(request: Request, binding: GeneratedRestBinding) -> object:
    media_type = request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
    if media_type != "application/json":
        raise RakitError(
            code=ErrorCode.VALIDATION_FAILED,
            message="Generated mutations require application/json.",
            status_code=415,
            details={
                "resource_id": binding.api.resource_id,
                "reason": "generated_api_json_required",
            },
        )
    body = await request.body()
    if len(body) > _MAX_JSON_BODY_BYTES:
        raise RakitError(
            code=ErrorCode.VALIDATION_FAILED,
            message="Generated mutation body is too large.",
            status_code=413,
            details={
                "resource_id": binding.api.resource_id,
                "reason": "generated_api_json_body_too_large",
            },
        )
    try:
        return json.loads(body)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RakitError(
            code=ErrorCode.VALIDATION_FAILED,
            message="Generated mutation body is invalid JSON.",
            status_code=400,
            details={
                "resource_id": binding.api.resource_id,
                "reason": "generated_api_json_invalid",
            },
        ) from exc


def _fingerprint_value(value: object) -> object:
    if value is None or isinstance(value, bool | int | str):
        return value
    if isinstance(value, float):
        return {"type": "float", "value": repr(value)}
    if isinstance(value, UUID):
        return {"type": "uuid", "value": str(value)}
    if isinstance(value, datetime):
        return {"type": "datetime", "value": value.isoformat()}
    if isinstance(value, date):
        return {"type": "date", "value": value.isoformat()}
    if isinstance(value, Decimal):
        return {"type": "decimal", "value": str(value)}
    if isinstance(value, Enum):
        return _fingerprint_value(value.value)
    if isinstance(value, Mapping):
        return {
            str(key): _fingerprint_value(item)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
        }
    if isinstance(value, list | tuple):
        return [_fingerprint_value(item) for item in value]
    raise RakitError(
        code=ErrorCode.CONFIG_INVALID,
        message="Generated mutation input cannot be fingerprinted.",
        status_code=500,
    )


def _mutation_fingerprint(
    binding: GeneratedRestBinding,
    generated_request: GeneratedCrudRequest,
) -> str:
    input_values = generated_request.input.values if generated_request.input is not None else {}
    present_fields = (
        sorted(generated_request.input.present_fields)
        if generated_request.input is not None
        else []
    )
    token_hash = (
        hashlib.sha256(generated_request.concurrency_token.encode()).hexdigest()
        if generated_request.concurrency_token is not None
        else None
    )
    payload = {
        "resource_id": binding.api.resource_id,
        "operation": generated_request.operation.value,
        "identity": (
            canonical_identity_payload(generated_request.identity)
            if generated_request.identity is not None
            else None
        ),
        "values": _fingerprint_value(input_values),
        "present_fields": present_fields,
        "concurrency_token_hash": token_hash,
    }
    return hashlib.sha256(
        json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
    ).hexdigest()


async def _claim_mutation(
    binding: GeneratedRestBinding,
    key: str,
    fingerprint: str,
    *,
    principal_id: str,
    operation: GeneratedCrudOperation,
) -> tuple[IdempotencyReservation, Response | None]:
    store = binding.idempotency_store
    if store is None:
        raise RakitError(
            code=ErrorCode.CONFIG_INVALID,
            message="Generated CRUD requires an idempotency store.",
            status_code=500,
        )
    try:
        token_scope = "\0".join(
            (
                binding.admin_id,
                principal_id,
                binding.api.resource_id,
                operation.value,
                key,
            )
        )
        reservation = await store.begin(
            hashlib.sha256(token_scope.encode()).hexdigest(),
            fingerprint=fingerprint,
        )
    except ValueError as exc:
        raise RakitError(
            code=ErrorCode.RESOURCE_CONFLICT,
            message="Idempotency key is bound to another mutation.",
            status_code=409,
        ) from exc
    if reservation.status is IdempotencyStatus.COMPLETED:
        return reservation, _replay_response(reservation)
    if not reservation.claimed:
        raise RakitError(
            code=ErrorCode.RESOURCE_CONFLICT,
            message="Mutation is already in progress.",
            status_code=409,
        )
    return reservation, None


def _receipt_payload(response: Response) -> Mapping[str, object]:
    body: object | None
    if response.status_code == 204:
        body = None
    elif isinstance(response, JSONResponse):
        raw_body = bytes(response.body).decode("utf-8")
        body = json.loads(raw_body)
    else:
        raise RakitError(
            code=ErrorCode.CONFIG_INVALID,
            message="Generated mutation response is not replayable.",
            status_code=500,
        )
    headers = {
        name: value
        for name, value in response.headers.items()
        if name.lower() in {"location", "etag", "cache-control"}
    }
    return {
        "status_code": response.status_code,
        "body": body,
        "headers": headers,
    }


def _replay_response(reservation: IdempotencyReservation) -> Response:
    receipt = reservation.completed_receipt
    if receipt is None or receipt.result_kind != "generated-rest" or receipt.payload is None:
        raise RakitError(
            code=ErrorCode.INTERNAL_ERROR,
            message="Stored generated mutation receipt is invalid.",
            status_code=500,
        )
    status_code = receipt.payload.get("status_code")
    body = receipt.payload.get("body")
    headers = receipt.payload.get("headers")
    if not isinstance(status_code, int) or not isinstance(headers, Mapping):
        raise RakitError(
            code=ErrorCode.INTERNAL_ERROR,
            message="Stored generated mutation receipt is invalid.",
            status_code=500,
        )
    normalized_headers = {
        str(name): str(value)
        for name, value in headers.items()
        if isinstance(name, str) and isinstance(value, str)
    }
    if status_code == 204:
        return Response(status_code=204, headers=normalized_headers)
    return JSONResponse(body, status_code=status_code, headers=normalized_headers)


async def _complete_mutation(
    binding: GeneratedRestBinding,
    reservation: IdempotencyReservation,
    response: Response,
    *,
    operation_id: str,
) -> None:
    assert binding.idempotency_store is not None
    await binding.idempotency_store.complete(
        reservation,
        OperationReceipt(
            operation_id=operation_id,
            status="succeeded",
            result_kind="generated-rest",
            payload=_receipt_payload(response),
        ),
    )


def _mutation_response(
    binding: GeneratedRestBinding,
    request: Request,
    operation: GeneratedCrudOperation,
    result: object,
) -> Response:
    if not isinstance(result, GeneratedMutationResult):
        raise RakitError(
            code=ErrorCode.INTERNAL_ERROR,
            message="Generated mutation executor returned an invalid result.",
            status_code=500,
        )
    if operation is GeneratedCrudOperation.DELETE:
        if result.record is not None:
            raise RakitError(
                code=ErrorCode.INTERNAL_ERROR,
                message="Generated delete returned an unexpected record.",
                status_code=500,
            )
        return Response(status_code=204, headers={"Cache-Control": "no-store"})
    if result.record is None:
        raise RakitError(
            code=ErrorCode.INTERNAL_ERROR,
            message="Generated mutation result is missing a record.",
            status_code=500,
        )
    body = {
        "data": serialize_generated_record(
            binding.api,
            result.record,
            schema_adapter=binding.schema_adapter,
        )
    }
    headers = {"Cache-Control": "no-store"}
    headers.update(_etag_headers(binding, result.identity, result.record))
    status_code = 200
    if operation is GeneratedCrudOperation.CREATE:
        status_code = 201
        headers["Location"] = mounted_path(
            request,
            f"/api/{binding.api.resource_id}/{binding.codec.encode(result.identity)}",
        )
    return JSONResponse(body, status_code=status_code, headers=headers)


async def _mutation_handler(
    binding: GeneratedRestBinding,
    request: Request,
    *,
    operation: GeneratedCrudOperation,
) -> Response:
    reservation: IdempotencyReservation | None = None
    try:
        identity = (
            _decode_identity(binding, request)
            if operation in {GeneratedCrudOperation.UPDATE_PARTIAL, GeneratedCrudOperation.DELETE}
            else None
        )
        permission = {
            GeneratedCrudOperation.CREATE: "create",
            GeneratedCrudOperation.UPDATE_PARTIAL: "update",
            GeneratedCrudOperation.DELETE: "delete",
        }[operation]
        authorization = _authorize_mutation(
            binding,
            request,
            operation=permission,
            identity=identity,
        )
        await _verify_mutation_csrf(binding, request)
        key = _idempotency_key(binding, request)

        if operation is GeneratedCrudOperation.CREATE:
            payload = await _json_payload(request, binding)
            generated_input = validate_generated_rest_payload(
                binding.api,
                operation,
                payload,
                binding.api.field_definitions,
                schema_adapter=binding.schema_adapter,
            )
            generated_request = GeneratedCrudRequest.create(generated_input)
        elif operation is GeneratedCrudOperation.UPDATE_PARTIAL:
            assert identity is not None
            payload = await _json_payload(request, binding)
            generated_input = validate_generated_rest_payload(
                binding.api,
                operation,
                payload,
                binding.api.field_definitions,
                schema_adapter=binding.schema_adapter,
            )
            if not generated_input.present_fields:
                raise RakitError(
                    code=ErrorCode.VALIDATION_FAILED,
                    message="Generated PATCH requires at least one field.",
                    status_code=422,
                    details={
                        "resource_id": binding.api.resource_id,
                        "reason": "generated_api_patch_empty",
                    },
                )
            generated_request = GeneratedCrudRequest.update_partial(
                identity,
                generated_input,
                concurrency_token=_if_match_token(binding, request),
            )
        else:
            assert identity is not None
            if await request.body():
                raise RakitError(
                    code=ErrorCode.VALIDATION_FAILED,
                    message="Generated delete does not accept a request body.",
                    status_code=400,
                    details={"reason": "generated_api_delete_body_not_allowed"},
                )
            generated_request = GeneratedCrudRequest.delete(
                identity,
                concurrency_token=_if_match_token(binding, request),
            )

        fingerprint = _mutation_fingerprint(binding, generated_request)
        reservation, replay = await _claim_mutation(
            binding,
            key,
            fingerprint,
            principal_id=authorization.principal_id,
            operation=operation,
        )
        if replay is not None:
            return replay
        result, operation_id = await _run_mutation(
            binding,
            request,
            generated_request,
            authorization,
            idempotency_fingerprint=fingerprint,
            reservation=reservation,
        )
        response = _mutation_response(binding, request, operation, result)
        await _complete_mutation(
            binding,
            reservation,
            response,
            operation_id=operation_id,
        )
        return response
    except RakitError as exc:
        return generated_error_response(request, exc)
    except Exception:
        return _unexpected_error_response(request)


def build_generated_rest_routes(
    binding: GeneratedRestBinding,
    *,
    include_reads: bool = True,
    include_mutations: bool = True,
) -> tuple[Route, ...]:
    routes: list[Route] = []

    async def list_resource(request: Request) -> JSONResponse:
        try:
            query = parse_generated_rest_query(
                binding.api,
                binding.definition.field_policy,
                request.query_params,
            )
            authorization = _authorize_read(binding, request, operation="list")
            result = await _run_read(
                binding,
                request,
                GeneratedCrudRequest.list(query),
                authorization,
            )
            return _list_response(binding, result)
        except RakitError as exc:
            return generated_error_response(request, exc)
        except Exception:
            return _unexpected_error_response(request)

    async def detail_resource(request: Request) -> JSONResponse:
        try:
            identity = _decode_identity(binding, request)
            authorization = _authorize_read(
                binding,
                request,
                operation="detail",
                identity=identity,
            )
            result = await _run_read(
                binding,
                request,
                GeneratedCrudRequest.detail(identity),
                authorization,
            )
            return _detail_response(binding, identity, result)
        except RakitError as exc:
            return generated_error_response(request, exc)
        except Exception:
            return _unexpected_error_response(request)

    async def create_resource(request: Request) -> Response:
        return await _mutation_handler(
            binding,
            request,
            operation=GeneratedCrudOperation.CREATE,
        )

    async def update_resource(request: Request) -> Response:
        return await _mutation_handler(
            binding,
            request,
            operation=GeneratedCrudOperation.UPDATE_PARTIAL,
        )

    async def delete_resource(request: Request) -> Response:
        return await _mutation_handler(
            binding,
            request,
            operation=GeneratedCrudOperation.DELETE,
        )

    base = f"/api/{binding.api.resource_id}"
    detail = f"{base}/{{identity}}"
    if include_reads and GeneratedCrudOperation.LIST in binding.api.operations:
        routes.append(
            Route(
                base,
                list_resource,
                methods=["GET"],
                name=f"generated-api:{binding.api.resource_id}:list",
            )
        )
    if include_reads and GeneratedCrudOperation.DETAIL in binding.api.operations:
        routes.append(
            Route(
                detail,
                detail_resource,
                methods=["GET"],
                name=f"generated-api:{binding.api.resource_id}:detail",
            )
        )
    if (
        include_mutations
        and GeneratedCrudOperation.CREATE in binding.api.operations
        and binding.generated_executor
    ):
        routes.append(
            Route(
                base,
                create_resource,
                methods=["POST"],
                name=f"generated-api:{binding.api.resource_id}:create",
            )
        )
    if (
        include_mutations
        and GeneratedCrudOperation.UPDATE_PARTIAL in binding.api.operations
        and binding.generated_executor
    ):
        routes.append(
            Route(
                detail,
                update_resource,
                methods=["PATCH"],
                name=f"generated-api:{binding.api.resource_id}:update",
            )
        )
    if (
        include_mutations
        and GeneratedCrudOperation.DELETE in binding.api.operations
        and binding.generated_executor
    ):
        routes.append(
            Route(
                detail,
                delete_resource,
                methods=["DELETE"],
                name=f"generated-api:{binding.api.resource_id}:delete",
            )
        )
    return tuple(routes)


def generated_rest_requirement_map(
    apis: tuple[CompiledResourceApi, ...],
    *,
    admin_id: str,
) -> dict[tuple[str, str], PermissionRequirement]:
    requirements: dict[tuple[str, str], PermissionRequirement] = {}
    for api in apis:
        base = f"/api/{api.resource_id}"
        detail = f"{base}/{{identity}}"
        read = PermissionRequirement.all_of(f"{admin_id}.resources.{api.resource_id}.read")
        if GeneratedCrudOperation.LIST in api.operations:
            requirements[("GET", base)] = read
            requirements[("HEAD", base)] = read
        if GeneratedCrudOperation.DETAIL in api.operations:
            requirements[("GET", detail)] = read
            requirements[("HEAD", detail)] = read
        if GeneratedCrudOperation.CREATE in api.operations:
            requirements[("POST", base)] = _permission_requirement_for(
                admin_id, api.resource_id, "create"
            )
        if GeneratedCrudOperation.UPDATE_PARTIAL in api.operations:
            requirements[("PATCH", detail)] = _permission_requirement_for(
                admin_id, api.resource_id, "update"
            )
        if GeneratedCrudOperation.DELETE in api.operations:
            requirements[("DELETE", detail)] = _permission_requirement_for(
                admin_id, api.resource_id, "delete"
            )
    return requirements


def _permission_requirement_for(
    admin_id: str,
    resource_id: str,
    permission: str,
) -> PermissionRequirement:
    return PermissionRequirement.all_of(f"{admin_id}.resources.{resource_id}.{permission}")


__all__ = [
    "GeneratedReadExecutor",
    "GeneratedRestBinding",
    "build_generated_rest_routes",
    "generated_error_response",
    "generated_rest_requirement_map",
]
