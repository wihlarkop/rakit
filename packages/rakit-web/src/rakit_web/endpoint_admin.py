"""Public composition and Admin integration for custom endpoints."""

from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from typing import Any, cast

from pydantic import BaseModel
from rakit_core.compiler import CompiledApplication
from rakit_core.crypto import TokenService
from rakit_core.definitions import EndpointDefinition
from rakit_core.di import ServiceKey, ServiceResolver
from rakit_core.endpoints import (
    AdminEndpoint,
    DomainEndpointHandler,
    EndpointAccessPolicy,
    EndpointContext,
    EndpointExecutionResult,
    EndpointInputSource,
    EndpointMethod,
    EndpointMutationHandler,
    EndpointResponseKind,
)
from rakit_core.errors import ErrorCode, RakitError
from rakit_core.idempotency import IdempotencyStore
from rakit_core.operations import resolve_operation_executor_capabilities
from rakit_core.transactions import OperationUnitOfWorkFactory, TransactionPolicy
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.types import ASGIApp, Receive, Scope, Send

from .admin import Admin as _BaseAdmin
from .admin import RequestContextMiddleware
from .auth_routes import _verify_csrf
from .endpoint_routes import EndpointBinding, build_endpoint_routes
from .security.authentication import PrincipalMiddleware, admin_relative_path
from .security.csrf import CsrfService
from .security.middleware import SecurityMiddleware
from .security.validation import validate_idempotency_store_for_production

type EndpointHandler = Callable[
    [EndpointContext],
    EndpointExecutionResult[Any] | Awaitable[EndpointExecutionResult[Any]],
]


def _endpoint_handler_name(handler: Callable[..., object]) -> str:
    name = getattr(handler, "__name__", None)
    if not isinstance(name, str) or not name:
        raise TypeError("Endpoint decorator handlers must have a stable function name")
    return name


class EndpointApi:
    """Decorator composition surface exposed as ``admin.api``."""

    def __init__(self, admin: "Admin") -> None:
        self._admin = admin

    def get(
        self,
        path: str,
        *,
        endpoint_id: str | None = None,
        input_schema: type[BaseModel] | None = None,
        input_source: EndpointInputSource | None = None,
        output_schema: type[BaseModel] | None = None,
        access_policy: EndpointAccessPolicy = EndpointAccessPolicy.PRIVATE,
        response_kind: EndpointResponseKind = EndpointResponseKind.JSON,
        allow_response_escape_hatch: bool = False,
    ) -> Callable[[Callable[..., object]], Callable[..., object]]:
        def decorator(handler: Callable[..., object]) -> Callable[..., object]:
            self._admin.register_endpoint(
                AdminEndpoint(
                    endpoint_id=endpoint_id or _endpoint_handler_name(handler),
                    path=path,
                    method=EndpointMethod.GET,
                    handler=handler,
                    input_schema=input_schema,
                    input_source=input_source,
                    output_schema=output_schema,
                    access_policy=access_policy,
                    response_kind=response_kind,
                    allow_response_escape_hatch=allow_response_escape_hatch,
                )
            )
            return handler

        return decorator

    def post(
        self,
        path: str,
        *,
        endpoint_id: str | None = None,
        input_schema: type[BaseModel] | None = None,
        input_source: EndpointInputSource | None = None,
        output_schema: type[BaseModel] | None = None,
        access_policy: EndpointAccessPolicy = EndpointAccessPolicy.PRIVATE,
        transaction_policy: TransactionPolicy = TransactionPolicy.AUTO,
    ) -> Callable[[Callable[..., object]], Callable[..., object]]:
        def decorator(handler: Callable[..., object]) -> Callable[..., object]:
            self._admin.register_endpoint(
                AdminEndpoint(
                    endpoint_id=endpoint_id or _endpoint_handler_name(handler),
                    path=path,
                    method=EndpointMethod.POST,
                    handler=handler,
                    input_schema=input_schema,
                    input_source=input_source,
                    output_schema=output_schema,
                    access_policy=access_policy,
                    transaction_policy=transaction_policy,
                )
            )
            return handler

        return decorator


def _definition_from_public(endpoint: AdminEndpoint) -> EndpointDefinition:
    method = endpoint.method
    typed_handler = cast("EndpointHandler", endpoint.handler)
    handler: object
    if method is EndpointMethod.POST:
        handler = (
            endpoint.handler
            if isinstance(endpoint.handler, EndpointMutationHandler)
            else EndpointMutationHandler(typed_handler)
        )
    else:
        handler = (
            endpoint.handler
            if isinstance(endpoint.handler, DomainEndpointHandler)
            else DomainEndpointHandler(typed_handler)
        )
    assert endpoint.transaction_policy is not None
    return EndpointDefinition(
        endpoint_id=endpoint.endpoint_id,
        path=endpoint.path,
        methods=(method,),
        input_schema=endpoint.input_schema,
        input_source=endpoint.input_source,
        output_schema=endpoint.output_schema,
        access_policy=endpoint.access_policy,
        response_kind=endpoint.response_kind,
        allow_response_escape_hatch=endpoint.allow_response_escape_hatch,
        handler=handler,
        mutating=method is EndpointMethod.POST,
        transaction_policy=endpoint.transaction_policy,
    )


def validate_endpoint_runtime(
    compiled: CompiledApplication,
    *,
    auth_enabled: bool,
    idempotency_store: IdempotencyStore | None,
    uow_factory_registered: bool,
    debug: bool,
) -> None:
    """Fail closed for endpoint combinations the runtime cannot safely guarantee."""

    if not compiled.compiled_endpoints:
        return

    post_endpoints = []
    for compiled_endpoint in compiled.compiled_endpoints:
        endpoint = compiled_endpoint.definition
        if "{" in endpoint.path or "}" in endpoint.path:
            raise RakitError(
                code=ErrorCode.CONFIG_INVALID,
                message=(
                    f'Endpoint "{endpoint.endpoint_id}" uses a parameterized path, but '
                    "Custom endpoint runtime supports static paths only."
                ),
                status_code=500,
                details={
                    "endpoint_id": str(endpoint.endpoint_id),
                    "reason": "path_parameters_not_supported",
                },
            )
        if len(endpoint.methods) != 1:
            raise RakitError(
                code=ErrorCode.CONFIG_INVALID,
                message="Custom endpoints must declare exactly one HTTP method.",
                status_code=500,
                details={"endpoint_id": str(endpoint.endpoint_id), "reason": "one_method_required"},
            )
        if endpoint.handler is None or not callable(endpoint.handler):
            raise RakitError(
                code=ErrorCode.CONFIG_INVALID,
                message=f'Endpoint "{endpoint.endpoint_id}" requires a callable handler.',
                status_code=500,
                details={"endpoint_id": str(endpoint.endpoint_id), "reason": "handler_missing"},
            )
        method = endpoint.methods[0]
        if endpoint.input_schema is not None and endpoint.input_source is None:
            raise RakitError(
                code=ErrorCode.CONFIG_INVALID,
                message="Typed endpoint input requires one explicit input source.",
                status_code=500,
                details={
                    "endpoint_id": str(endpoint.endpoint_id),
                    "reason": "input_source_missing",
                },
            )
        if method is EndpointMethod.GET:
            if endpoint.mutating or endpoint.transaction_policy is not TransactionPolicy.READ_ONLY:
                raise RakitError(
                    code=ErrorCode.CONFIG_INVALID,
                    message="GET endpoints must be read-only.",
                    status_code=500,
                    details={
                        "endpoint_id": str(endpoint.endpoint_id),
                        "reason": "get_not_read_only",
                    },
                )
            if endpoint.input_source not in (None, EndpointInputSource.QUERY):
                raise RakitError(
                    code=ErrorCode.CONFIG_INVALID,
                    message="GET endpoints accept QUERY input only.",
                    status_code=500,
                    details={
                        "endpoint_id": str(endpoint.endpoint_id),
                        "reason": "get_input_source",
                    },
                )
        else:
            post_endpoints.append(compiled_endpoint)
            if not endpoint.mutating or endpoint.transaction_policy is TransactionPolicy.READ_ONLY:
                raise RakitError(
                    code=ErrorCode.CONFIG_INVALID,
                    message="POST endpoints must be mutating and transactional.",
                    status_code=500,
                    details={
                        "endpoint_id": str(endpoint.endpoint_id),
                        "reason": "post_not_mutating",
                    },
                )
            if endpoint.access_policy is EndpointAccessPolicy.PUBLIC:
                raise RakitError(
                    code=ErrorCode.CONFIG_INVALID,
                    message="Public POST endpoints are not supported by the current runtime.",
                    status_code=500,
                    details={
                        "endpoint_id": str(endpoint.endpoint_id),
                        "reason": "public_post_not_supported",
                    },
                )
            if endpoint.input_source not in (
                None,
                EndpointInputSource.JSON,
                EndpointInputSource.FORM,
            ):
                raise RakitError(
                    code=ErrorCode.CONFIG_INVALID,
                    message="POST endpoints accept JSON or FORM input only.",
                    status_code=500,
                    details={
                        "endpoint_id": str(endpoint.endpoint_id),
                        "reason": "post_input_source",
                    },
                )
            if endpoint.response_kind is not EndpointResponseKind.JSON:
                raise RakitError(
                    code=ErrorCode.CONFIG_INVALID,
                    message="POST endpoint responses must be replayable JSON.",
                    status_code=500,
                    details={
                        "endpoint_id": str(endpoint.endpoint_id),
                        "reason": "post_response_kind",
                    },
                )
            capabilities = resolve_operation_executor_capabilities(endpoint.handler)
            if endpoint.transaction_policy in (TransactionPolicy.AUTO, TransactionPolicy.MANUAL):
                if not capabilities.participates_in_uow:
                    raise RakitError(
                        code=ErrorCode.CONFIG_INVALID,
                        message=(
                            f'Endpoint "{endpoint.endpoint_id}" declares '
                            f"{endpoint.transaction_policy.value} transaction policy but its "
                            "handler does not participate in the operation unit of work."
                        ),
                        status_code=500,
                        details={
                            "endpoint_id": str(endpoint.endpoint_id),
                            "reason": "handler_not_uow_managed",
                        },
                    )
                if not uow_factory_registered:
                    raise RakitError(
                        code=ErrorCode.CONFIG_INVALID,
                        message=(
                            f'Endpoint "{endpoint.endpoint_id}" requires a registered operation '
                            "unit-of-work provider."
                        ),
                        status_code=500,
                        details={
                            "endpoint_id": str(endpoint.endpoint_id),
                            "reason": "operation_uow_not_configured",
                        },
                    )
        if endpoint.response_kind is EndpointResponseKind.ADVANCED:
            raise RakitError(
                code=ErrorCode.CONFIG_INVALID,
                message="Advanced raw response adapters are not supported.",
                status_code=500,
                details={
                    "endpoint_id": str(endpoint.endpoint_id),
                    "reason": "advanced_response_deferred",
                },
            )
        if endpoint.response_kind in (EndpointResponseKind.FILE, EndpointResponseKind.STREAM) and (
            method is not EndpointMethod.GET
            or endpoint.transaction_policy is not TransactionPolicy.READ_ONLY
        ):
            raise RakitError(
                code=ErrorCode.CONFIG_INVALID,
                message="File and stream endpoints must be read-only GET operations.",
                status_code=500,
                details={
                    "endpoint_id": str(endpoint.endpoint_id),
                    "reason": "streaming_transaction_boundary",
                },
            )

    private_endpoints = [
        item
        for item in compiled.compiled_endpoints
        if item.definition.access_policy is EndpointAccessPolicy.PRIVATE
    ]
    if private_endpoints and not auth_enabled:
        raise RakitError(
            code=ErrorCode.CONFIG_INVALID,
            message="Private custom endpoints require configured authentication.",
            status_code=500,
        )
    if post_endpoints and idempotency_store is None:
        raise RakitError(
            code=ErrorCode.CONFIG_INVALID,
            message=(
                "POST endpoints require an operation idempotency store "
                "(Admin(operation_idempotency_store=...))."
            ),
            status_code=500,
        )
    if post_endpoints and idempotency_store is not None:
        validate_idempotency_store_for_production(idempotency_store, debug=debug)


class _EndpointDispatchMiddleware:
    """Send exact compiled endpoint paths to the API pipeline; delegate everything else."""

    def __init__(self, base_app: ASGIApp, endpoint_app: ASGIApp, paths: frozenset[str]) -> None:
        self.base_app = base_app
        self.endpoint_app = endpoint_app
        self.paths = paths

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.base_app(scope, receive, send)
            return
        request = Request(scope, receive=receive)
        if admin_relative_path(request) in self.paths:
            await self.endpoint_app(scope, receive, send)
            return
        await self.base_app(scope, receive, send)


class Admin(_BaseAdmin):
    """Endpoint-enabled public Admin facade.

    The base Starlette admin remains unchanged; custom endpoints add an exact-path API
    dispatch layer so API authentication failures stay JSON instead of
    inheriting browser redirect/plain-text behavior.
    """

    @property
    def api(self) -> EndpointApi:
        return EndpointApi(self)

    def register_endpoint(self, endpoint: AdminEndpoint) -> None:
        if self.compiled is not None:
            raise RuntimeError("Cannot register endpoints after compilation")
        self.builder.add_endpoint(_definition_from_public(endpoint))

    def asgi(self) -> ASGIApp:
        base_app = super().asgi()
        compiled = self.compile()
        if not compiled.compiled_endpoints:
            return base_app

        auth_enabled = self._auth_backend is not None and self._session_store is not None
        uow_factory_registered = (
            self._compiled_registry is not None
            and ServiceKey(OperationUnitOfWorkFactory, None) in self._compiled_registry.providers
        )
        validate_endpoint_runtime(
            compiled,
            auth_enabled=auth_enabled,
            idempotency_store=self._operation_idempotency_store,
            uow_factory_registered=uow_factory_registered,
            debug=self.config.debug,
        )

        route_by_name = {route.route_name: route for route in compiled.routes}
        pairs = tuple(
            (
                route_by_name[f"endpoint:{compiled_endpoint.definition.endpoint_id}"],
                compiled_endpoint,
            )
            for compiled_endpoint in compiled.compiled_endpoints
        )

        @asynccontextmanager
        async def operation_scope() -> AsyncIterator[ServiceResolver]:
            if self._application_resolver is None:
                raise RuntimeError("Application services are not available")
            async with (
                self._application_resolver.request_scope() as request_services,
                request_services.operation_scope() as operation_services,
            ):
                yield operation_services

        def unit_of_work_factory() -> OperationUnitOfWorkFactory | None:
            if self._application_resolver is None:
                return None
            return self._application_resolver.require(OperationUnitOfWorkFactory)

        verify_csrf: Callable[[Request], Awaitable[bool]] | None = None
        if any(
            EndpointMethod.POST in item.definition.methods for item in compiled.compiled_endpoints
        ):
            if (
                self.config.security.secret_key is None
                or self._auth_backend is None
                or self._session_store is None
            ):
                raise RakitError(
                    code=ErrorCode.CONFIG_INVALID,
                    message=(
                        "POST custom endpoints require session authentication and a secret key."
                    ),
                    status_code=500,
                )
            token_service = TokenService.single_key(
                key_id="primary",
                value=self.config.security.secret_key,
                admin_id=self.config.admin_id,
            )
            csrf_service = CsrfService(token_service)

            async def verify_endpoint_csrf(request: Request) -> bool:
                session_id = request.scope.get("state", {}).get("session_id")
                return isinstance(session_id, str) and await _verify_csrf(
                    request,
                    csrf_service,
                    session_id=session_id,
                )

            verify_csrf = verify_endpoint_csrf

        binding = EndpointBinding(
            routes=pairs,
            admin_id=self.config.admin_id,
            superuser_bypass=self._superuser_bypass,
            verify_csrf=verify_csrf,
            idempotency_store=self._operation_idempotency_store,
            deadline_seconds=self._mutation_deadline_seconds,
            operation_scope=operation_scope,
            unit_of_work_factory=unit_of_work_factory,
        )
        endpoint_app: ASGIApp = Starlette(routes=build_endpoint_routes(binding))
        if auth_enabled:
            assert self._auth_backend is not None
            assert self._session_store is not None
            endpoint_app = PrincipalMiddleware(
                endpoint_app,
                auth_backend=self._auth_backend,
                session_store=self._session_store,
            )
        endpoint_app = SecurityMiddleware(
            endpoint_app,
            allowed_hosts=self.config.security.allowed_hosts,
            content_security_policy_enabled=self.config.security.content_security_policy_enabled,
        )
        endpoint_app = RequestContextMiddleware(endpoint_app, admin_id=self.config.admin_id)
        endpoint_paths = frozenset(
            str(item.definition.path) for item in compiled.compiled_endpoints
        )
        return _EndpointDispatchMiddleware(base_app, endpoint_app, endpoint_paths)


__all__ = ["Admin", "EndpointApi", "validate_endpoint_runtime"]
