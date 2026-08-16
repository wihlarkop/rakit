from dataclasses import dataclass, field

from rakit_core.auth import Principal
from rakit_core.definitions import ResourceDefinition
from rakit_core.errors import ErrorCode, RakitError
from rakit_core.generated_api import CompiledResourceApi, GeneratedCrudOperation
from rakit_core.generated_operations import (
    GeneratedCrudRequest,
    GeneratedResourceExecutor,
    build_generated_operation_plan,
)
from rakit_core.identity import IdentityCodec, RecordIdentity
from rakit_core.mutations import OperationAuthorization
from rakit_core.operations import (
    CancellationContext,
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
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from .generated_rest import (
    generated_error_payload,
    parse_generated_rest_query,
    serialize_generated_record,
)

_PUBLIC_READ_ACTOR = "rakit:public-read"


def _request_id(request: Request) -> str:
    value = request.scope.get("state", {}).get("request_id", "")
    return value if isinstance(value, str) else ""


def generated_error_response(request: Request, error: RakitError) -> JSONResponse:
    return JSONResponse(
        generated_error_payload(error, request_id=_request_id(request)),
        status_code=error.status_code,
        headers={"Cache-Control": "no-store"},
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


def _read_requirement(binding: GeneratedRestBinding) -> PermissionRequirement:
    return PermissionRequirement.all_of(
        f"{binding.admin_id}.resources.{binding.api.resource_id}.read"
    )


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


async def _run_read(
    binding: GeneratedRestBinding,
    request: Request,
    generated_request: GeneratedCrudRequest,
    authorization: OperationAuthorization,
) -> object:
    executor: GeneratedResourceExecutor = GeneratedReadExecutor(binding.service)
    plan = build_generated_operation_plan(binding.api, generated_request, authorization, executor)
    context = OperationContext(
        deadline=None,
        cancellation=CancellationContext(),
        request_id=_request_id(request),
        operation_id=new_operation_id(),
        principal=_principal(request),
        principal_id=authorization.principal_id,
        admin_id=authorization.admin_id,
        resource_id=authorization.resource_id,
        operation=authorization.operation,
        permissions=authorization.permissions,
        permission_requirement=authorization.requirement,
    )
    with activate_operation_context(context):
        return await run_operation_plan(plan, context, unit_of_work_factory=None)


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


def _detail_response(binding: GeneratedRestBinding, result: object) -> JSONResponse:
    return JSONResponse(
        {
            "data": serialize_generated_record(
                binding.api,
                result,
                schema_adapter=binding.schema_adapter,
            )
        },
        headers={"Cache-Control": "no-store"},
    )


def build_generated_rest_routes(binding: GeneratedRestBinding) -> tuple[Route, ...]:
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

    async def detail_resource(request: Request) -> JSONResponse:
        try:
            raw_identity = request.path_params.get("identity")
            if not isinstance(raw_identity, str):
                raise RakitError(
                    code=ErrorCode.VALIDATION_FAILED,
                    message="Generated API identity is required.",
                    status_code=400,
                )
            try:
                identity = binding.codec.decode(raw_identity)
            except ValueError as exc:
                raise RakitError(
                    code=ErrorCode.VALIDATION_FAILED,
                    message="Generated API identity is invalid.",
                    status_code=400,
                    details={"reason": "generated_api_identity_invalid"},
                ) from exc
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
            return _detail_response(binding, result)
        except RakitError as exc:
            return generated_error_response(request, exc)

    if GeneratedCrudOperation.LIST in binding.api.operations:
        routes.append(
            Route(
                f"/api/{binding.api.resource_id}",
                list_resource,
                methods=["GET"],
                name=f"generated-api:{binding.api.resource_id}:list",
            )
        )
    if GeneratedCrudOperation.DETAIL in binding.api.operations:
        routes.append(
            Route(
                f"/api/{binding.api.resource_id}/{{identity}}",
                detail_resource,
                methods=["GET"],
                name=f"generated-api:{binding.api.resource_id}:detail",
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
        read = PermissionRequirement.all_of(f"{admin_id}.resources.{api.resource_id}.read")
        if GeneratedCrudOperation.LIST in api.operations:
            requirements[("GET", base)] = read
        if GeneratedCrudOperation.DETAIL in api.operations:
            requirements[("GET", f"{base}/{{identity}}")] = read
        if GeneratedCrudOperation.CREATE in api.operations:
            requirements[("POST", base)] = PermissionRequirement.all_of(
                f"{admin_id}.resources.{api.resource_id}.create"
            )
        if GeneratedCrudOperation.UPDATE_PARTIAL in api.operations:
            requirements[("PATCH", f"{base}/{{identity}}")] = PermissionRequirement.all_of(
                f"{admin_id}.resources.{api.resource_id}.update"
            )
        if GeneratedCrudOperation.DELETE in api.operations:
            requirements[("DELETE", f"{base}/{{identity}}")] = PermissionRequirement.all_of(
                f"{admin_id}.resources.{api.resource_id}.delete"
            )
    return requirements


__all__ = [
    "GeneratedReadExecutor",
    "GeneratedRestBinding",
    "build_generated_rest_routes",
    "generated_error_response",
    "generated_rest_requirement_map",
]
