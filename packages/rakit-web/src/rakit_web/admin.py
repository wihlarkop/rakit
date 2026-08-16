import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from dataclasses import replace
from datetime import timedelta
from math import isfinite
from pathlib import Path
from types import SimpleNamespace

import structlog
from rakit_core.actions import ActionDefinition, ActionScope
from rakit_core.admin_types import ModelAdmin, ResourceAdmin
from rakit_core.auth import AuthBackend, SessionStore
from rakit_core.compiler import ApplicationBuilder, CompiledApplication, Plugin, compile_application
from rakit_core.concurrency import ConcurrencyTokenService, ConcurrencyVersionProvider
from rakit_core.config import RakitConfig, SecretValue
from rakit_core.crypto import TokenService
from rakit_core.definitions import (
    CompiledActionDefinition,
    PageDefinition,
    ResourceDefinition,
    ResourceFieldPolicy,
    RouteDefinition,
)
from rakit_core.di import ServiceKey, ServiceRegistry, ServiceResolver, ServiceScope
from rakit_core.errors import ErrorCode, RakitError
from rakit_core.events import EventBus, EventPublisher
from rakit_core.idempotency import IdempotencyStore
from rakit_core.identity import IdentityCodec, RecordIdentity
from rakit_core.mutations import (
    MutationAuthorization,
    MutationOperation,
    OperationAuthorization,
    OperationAuthorizationSet,
)
from rakit_core.operations import resolve_operation_executor_capabilities
from rakit_core.relationship_mutations import (
    CreateRelated,
    DeleteRelated,
    RelationshipChangePlan,
    UpdateRelated,
)
from rakit_core.resources import ResourceService
from rakit_core.schema import SchemaAdapter
from rakit_core.transactions import OperationUnitOfWorkFactory, TransactionPolicy
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, PlainTextResponse
from starlette.routing import Mount, Route
from starlette.templating import Jinja2Templates
from starlette.types import ASGIApp, Receive, Scope, Send

from .action_routes import (
    ActionBinding,
    AdvancedActionResponseAdapter,
    build_action_routes,
)
from .assets import static_files
from .auth_routes import _verify_csrf, build_auth_routes
from .bulk_admin import build_admin_bulk_action_routes
from .capabilities import STARLETTE_WEB_CAPABILITIES
from .form_routes import WriteResourceBinding, build_write_routes
from .generated_rest_runtime import (
    GeneratedRestBinding,
    build_generated_rest_routes,
    generated_rest_requirement_map,
)
from .lifecycle import LifecycleManager
from .logging import bind_request_context, configure_logging, reset_request_context
from .page_admin import (
    build_admin_page_routes,
    page_requirement_map,
    register_public_page,
    validate_page_runtime,
)
from .public_composition import resource_actions, resource_relationships
from .relationship_routes import build_relationship_routes
from .resource_routes import ResourceBinding, build_resource_routes, build_templates
from .schema import PydanticSchemaAdapter
from .security.authentication import (
    LOGIN_PATH,
    LOGOUT_PATH,
    AuthorizationMiddleware,
    PrincipalMiddleware,
    build_requirement_resolver,
)
from .security.csrf import CsrfService
from .security.middleware import SecurityMiddleware
from .security.rate_limit import LoginRateLimiter, RateLimiter
from .security.validation import (
    parse_trusted_proxy_networks,
    validate_idempotency_store_for_production,
    validate_production_config,
    validate_rate_limiter_for_production,
    validate_session_store_for_production,
)

_FIELD_POLICY_NAMES = (
    "list_fields",
    "detail_fields",
    "filter_fields",
    "search_fields",
    "sort_fields",
)


def _invalid_field_policy(resource_id: str, policy_name: str) -> RakitError:
    return RakitError(
        code=ErrorCode.CONFIG_INVALID_RESOURCE_POLICY,
        message="Invalid resource field policy declaration",
        status_code=500,
        details={
            "resource_id": resource_id,
            "policy": policy_name,
            "reason": "fields_invalid",
        },
    )


def _normalize_field_policy(admin_cls: type[ResourceAdmin]) -> ResourceFieldPolicy:
    resource_id = admin_cls.resource_id
    normalized: dict[str, tuple[str, ...]] = {}
    for policy_name in _FIELD_POLICY_NAMES:
        raw_fields = getattr(admin_cls, policy_name, ())
        if not isinstance(raw_fields, list | tuple) or not all(
            isinstance(field_name, str) for field_name in raw_fields
        ):
            raise _invalid_field_policy(resource_id, policy_name)
        normalized[policy_name] = tuple(raw_fields)
    try:
        return ResourceFieldPolicy(**normalized)
    except (TypeError, ValueError):
        # Keep Pydantic implementation details and declaration values out of
        # the public configuration boundary.
        raise _invalid_field_policy(resource_id, policy_name) from None


logger = structlog.get_logger(__name__)


class RequestContextMiddleware:
    """Raw ASGI middleware that binds request-scoped context via structlog contextvars.

    A raw ASGI wrapper is used instead of ``BaseHTTPMiddleware`` because the
    latter runs the downstream app inside a separate anyio task, which is a
    known source of contextvars-propagation bugs across Starlette versions.
    Wrapping the ASGI callable directly keeps everything in the same task, so
    contextvars set before calling the inner app are reliably visible to
    structlog calls made while handling the request.
    """

    def __init__(self, app: ASGIApp, *, admin_id: str) -> None:
        self.app = app
        self.admin_id = admin_id

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request_id = str(uuid.uuid4())
        scope.setdefault("state", {})["request_id"] = request_id
        tokens = bind_request_context(request_id=request_id, admin_id=self.admin_id)
        try:
            logger.info("http.request.started", path=scope.get("path"))
            await self.app(scope, receive, send)
        finally:
            reset_request_context(tokens)


class Admin:
    def __init__(
        self,
        *,
        admin_id: str = "admin",
        title: str,
        debug: bool = False,
        secret_key: SecretValue | None = None,
        template_dirs: tuple[Path, ...] = (),
        auth_backend: AuthBackend | None = None,
        session_store: SessionStore | None = None,
        login_rate_limiter: RateLimiter | None = None,
        allowed_hosts: tuple[str, ...] | None = None,
        content_security_policy_enabled: bool = True,
        trusted_proxies: tuple[str, ...] = (),
        superuser_bypass: bool = True,
        mutation_deadline_seconds: float = 30.0,
        event_bus: EventBus | None = None,
        operation_idempotency_store: IdempotencyStore | None = None,
        advanced_action_response_adapter: AdvancedActionResponseAdapter | None = None,
        schema_adapter: SchemaAdapter | None = None,
    ) -> None:
        security_config: dict[str, object] = {
            "secret_key": secret_key,
            "content_security_policy_enabled": content_security_policy_enabled,
            "trusted_proxies": trusted_proxies,
        }
        if allowed_hosts is not None:
            security_config["allowed_hosts"] = allowed_hosts
        self.config = RakitConfig(
            admin_id=admin_id,
            title=title,
            debug=debug,
            security=security_config,
        )
        self._trusted_proxy_networks = parse_trusted_proxy_networks(
            self.config.security.trusted_proxies
        )
        validate_production_config(self.config, trusted_proxy_networks=self._trusted_proxy_networks)
        if (auth_backend is None) != (session_store is None):
            raise RakitError(
                code=ErrorCode.CONFIG_INVALID,
                message=(
                    "auth_backend and session_store must both be supplied together, or "
                    "both omitted -- a partial auth configuration would silently leave "
                    "the admin unauthenticated rather than failing closed."
                ),
                status_code=500,
            )
        self._auth_backend = auth_backend
        self._session_store = session_store
        self._superuser_bypass = superuser_bypass
        if (
            not isinstance(mutation_deadline_seconds, int | float)
            or not isfinite(mutation_deadline_seconds)
            or mutation_deadline_seconds <= 0
        ):
            raise RakitError(
                code=ErrorCode.CONFIG_INVALID,
                message="mutation_deadline_seconds must be a positive finite number.",
                status_code=500,
            )
        self._mutation_deadline_seconds = float(mutation_deadline_seconds)
        self._login_rate_limiter = login_rate_limiter or LoginRateLimiter()
        validate_rate_limiter_for_production(
            self._login_rate_limiter,
            debug=debug,
            auth_enabled=auth_backend is not None,
        )
        validate_session_store_for_production(
            session_store,
            debug=debug,
            auth_enabled=auth_backend is not None,
        )
        self._builder = ApplicationBuilder(admin_id=admin_id)
        self._builder.register_capability_provider(STARLETTE_WEB_CAPABILITIES)
        self._schema_adapter = schema_adapter or PydanticSchemaAdapter()
        self._builder.register_capability_provider(self._schema_adapter.provider)
        self._builder.registry.add_value(
            SchemaAdapter, self._schema_adapter, scope=ServiceScope.APPLICATION
        )
        self._operation_idempotency_store = operation_idempotency_store
        self._advanced_action_response_adapter = advanced_action_response_adapter
        self._concurrency_providers: dict[str, ConcurrencyVersionProvider] = {}
        self._event_bus = event_bus if event_bus is not None else EventBus()
        self._builder.registry.add_value(EventBus, self._event_bus, scope=ServiceScope.APPLICATION)
        self._builder.registry.add_factory(
            EventPublisher,
            lambda resolver: EventPublisher(resolver.require(EventBus)),
            scope=ServiceScope.OPERATION,
        )
        self._builder.add_route(
            RouteDefinition(
                route_name="rakit.home",
                methods=("GET",),
                path="/",
                owner_id="rakit",
                framework_owned=True,
            )
        )
        if auth_backend is not None and session_store is not None:
            # The auth routes are attached to the Starlette app at `asgi()`
            # time, but they must also exist in the compiled route graph:
            # otherwise `rakit routes` under-reports what is actually served,
            # and the compiler's collision checks are blind to routes that
            # really do occupy those paths at runtime.
            for route_name, methods, path in (
                ("rakit.auth.login", ("GET",), LOGIN_PATH),
                ("rakit.auth.login.submit", ("POST",), LOGIN_PATH),
                ("rakit.auth.logout", ("POST",), LOGOUT_PATH),
            ):
                self._builder.add_route(
                    RouteDefinition(
                        route_name=route_name,
                        methods=methods,
                        path=path,
                        owner_id="rakit",
                        framework_owned=True,
                    )
                )
        self.compiled: CompiledApplication | None = None
        self._compiled_registry: ServiceRegistry | None = None
        self._application_resolver: ServiceResolver | None = None
        self._resource_services: dict[str, ResourceService] = {}
        self._resource_definitions: dict[str, ResourceDefinition] = {}
        self._write_resource_bindings: dict[str, WriteResourceBinding] = {}
        self._template_dirs = template_dirs
        self.lifecycle = LifecycleManager()
        self.lifecycle.register_stopping_callback(self._close_application_resolver)

    @property
    def builder(self) -> ApplicationBuilder:
        return self._builder

    @property
    def event_bus(self) -> EventBus:
        """The application-scoped bus used by every mutation operation."""
        return self._event_bus

    def install(self, plugin: Plugin) -> None:
        if self.compiled is not None:
            raise RuntimeError("Cannot install plugins after compilation")
        self._builder.install(plugin)

    def register_page(
        self,
        definition: PageDefinition,
        *,
        actions: tuple[ActionDefinition, ...] = (),
    ) -> None:
        """Register one public custom Page declaration and its PAGE actions."""

        if self.compiled is not None:
            raise RuntimeError("Cannot register pages after compilation")
        register_public_page(self._builder, definition, actions=actions)

    def register(self, admin_cls: type[ResourceAdmin]) -> None:
        if self.compiled is not None:
            raise RuntimeError("Cannot register resources after compilation")

        for attribute_name in ("resource_id", "path", "label", "singular_label"):
            try:
                value = getattr(admin_cls, attribute_name)
            except AttributeError:
                raise RakitError(
                    code=ErrorCode.VALIDATION_FAILED,
                    message=(
                        f'{admin_cls.__name__} is missing required attribute "{attribute_name}".'
                    ),
                    status_code=500,
                    details={"admin_class": admin_cls.__name__, "attribute": attribute_name},
                ) from None
            if not isinstance(value, str) or not value:
                raise RakitError(
                    code=ErrorCode.VALIDATION_FAILED,
                    message=(f"{admin_cls.__name__}.{attribute_name} must be a non-empty string."),
                    status_code=500,
                    details={"admin_class": admin_cls.__name__, "attribute": attribute_name},
                )

        field_policy = _normalize_field_policy(admin_cls)
        relationships = resource_relationships(admin_cls)
        actions = resource_actions(
            admin_cls,
            existing_action_ids={str(action.action_id) for action in self._builder.actions},
        )

        if issubclass(admin_cls, ModelAdmin):
            claims = [
                result
                for claim in self._builder._adapters.values()
                if (result := claim(admin_cls.model, field_policy)) is not None
            ]
            if len(claims) == 0:
                raise RakitError(
                    code=ErrorCode.CONFIG_ADAPTER_NOT_FOUND,
                    message=(
                        f'No installed adapter could claim model "{admin_cls.model!r}" for '
                        f'"{admin_cls.__name__}".'
                    ),
                    status_code=500,
                    details={"admin_class": admin_cls.__name__},
                )
            if len(claims) > 1:
                raise RakitError(
                    code=ErrorCode.CONFIG_ADAPTER_AMBIGUOUS,
                    message=(
                        f'Multiple installed adapters claimed model "{admin_cls.model!r}" for '
                        f'"{admin_cls.__name__}".'
                    ),
                    status_code=500,
                    details={"admin_class": admin_cls.__name__, "claim_count": len(claims)},
                )
            data_source = claims[0]
        elif admin_cls.data_source is not None:
            data_source = admin_cls.data_source
        else:
            raise RakitError(
                code=ErrorCode.CONFIG_RESOURCE_MISSING_DATA_SOURCE,
                message=(
                    f'"{admin_cls.__name__}" has no data source: it is not a ModelAdmin '
                    "and no data_source was supplied."
                ),
                status_code=500,
                details={"admin_class": admin_cls.__name__},
            )

        definition = ResourceDefinition(
            resource_id=admin_cls.resource_id,
            path=admin_cls.path,
            label=admin_cls.label,
            singular_label=admin_cls.singular_label,
            field_policy=field_policy,
            relationships=relationships,
            api=admin_cls.api,
        )
        self._builder.add_resource(definition, data_source)
        for action in actions:
            self._builder.add_action(action)
        self._builder.add_route(
            RouteDefinition(
                route_name=f"resource:{definition.resource_id}:list",
                methods=("GET",),
                path=definition.path,
                owner_id=definition.resource_id,
            )
        )
        self._builder.add_route(
            RouteDefinition(
                route_name=f"resource:{definition.resource_id}:count",
                methods=("GET",),
                path=f"{definition.path}/_count",
                owner_id=definition.resource_id,
            )
        )
        self._builder.add_route(
            RouteDefinition(
                route_name=f"resource:{definition.resource_id}:detail",
                methods=("GET",),
                path=f"{definition.path}/{{identity}}",
                owner_id=definition.resource_id,
            )
        )
        self._resource_services[admin_cls.resource_id] = ResourceService(data_source)
        self._resource_definitions[admin_cls.resource_id] = definition

    def register_concurrency_provider(
        self, resource_id: str, provider: ConcurrencyVersionProvider
    ) -> None:
        """Register the backend-neutral concurrency provider for one resource.

        RECORD actions declaring ``requires_concurrency`` are served through
        this provider: the provider supplies the record version bound into
        the signed concurrency token (issued at GET, verified against fresh
        scoped state at POST). Registration is resource-level, pre-compile,
        and never guessed from adapters.
        """
        if self.compiled is not None:
            raise RuntimeError("Cannot register concurrency providers after compilation")
        if resource_id not in self._resource_services:
            raise RakitError(
                code=ErrorCode.CONFIG_INVALID,
                message=(f'Concurrency provider references unknown resource "{resource_id}".'),
                status_code=500,
                details={"resource_id": resource_id, "reason": "unknown_resource"},
            )
        if resource_id in self._concurrency_providers:
            raise RakitError(
                code=ErrorCode.CONFIG_INVALID,
                message=(f'Resource "{resource_id}" already has a concurrency provider.'),
                status_code=500,
                details={"resource_id": resource_id, "reason": "duplicate_provider"},
            )
        missing_members = tuple(
            name
            for name in ("version_for", "predicate_values_for", "next_values_for")
            if not callable(getattr(provider, name, None))
        )
        if missing_members:
            raise RakitError(
                code=ErrorCode.CONFIG_INVALID,
                message=(
                    f'Concurrency provider for resource "{resource_id}" does not '
                    "implement the full ConcurrencyVersionProvider contract "
                    f"(missing or non-callable: {', '.join(missing_members)})."
                ),
                status_code=500,
                details={
                    "resource_id": resource_id,
                    "reason": "invalid_provider_contract",
                    "members": missing_members,
                },
            )
        self._concurrency_providers[resource_id] = provider

    def register_write_resource(self, resource_id: str, binding: WriteResourceBinding) -> None:
        """Register the explicit Plan 04 write policy for an existing resource.

        Read registration never implies writability. A resource becomes
        mutable only through this separate, immutable form binding and only
        for an auth-enabled admin.
        """
        if self.compiled is not None:
            raise RuntimeError("Cannot register write resources after compilation")
        definition = self._resource_definitions.get(resource_id)
        if definition is None or binding.path != definition.path:
            raise RakitError(
                code=ErrorCode.CONFIG_INVALID_RESOURCE_POLICY,
                message="Invalid resource write policy declaration",
                status_code=500,
                details={"resource_id": resource_id, "reason": "resource_mismatch"},
            )
        if self._auth_backend is None or self._session_store is None:
            raise RakitError(
                code=ErrorCode.CONFIG_INVALID,
                message="Write resources require configured authentication.",
                status_code=500,
            )
        if binding.idempotency_store is None:
            raise RakitError(
                code=ErrorCode.CONFIG_INVALID,
                message="Write resources require a durable idempotency store.",
                status_code=500,
            )
        validate_idempotency_store_for_production(
            binding.idempotency_store, debug=self.config.debug
        )
        declared_event_bus = getattr(binding.mutation_service, "event_bus", None)
        if declared_event_bus is not None and declared_event_bus is not self._event_bus:
            raise RakitError(
                code=ErrorCode.CONFIG_INVALID,
                message="Mutation service event bus must match the Admin event bus.",
                status_code=500,
                details={"resource_id": resource_id, "reason": "event_bus_mismatch"},
            )
        bind_scope = getattr(binding.mutation_service, "bind_scoped_statement", None)
        scoped_statement = getattr(
            self._resource_services[resource_id].data_source, "scoped_statement", None
        )
        if callable(bind_scope) and callable(scoped_statement):
            bind_scope(scoped_statement)
        delete_capable = all(
            callable(getattr(binding.mutation_service, name, None))
            for name in ("issue_delete_token", "delete")
        )
        if delete_capable:
            bind_nonce_store = getattr(binding.mutation_service, "bind_delete_nonce_store", None)
            if not callable(bind_nonce_store):
                raise RakitError(
                    code=ErrorCode.CONFIG_INVALID_RESOURCE_POLICY,
                    message="Delete resources require durable confirmation storage.",
                    status_code=500,
                    details={"resource_id": resource_id, "reason": "missing_delete_nonce_store"},
                )
            bind_nonce_store(binding.idempotency_store)
        if resource_id in self._write_resource_bindings:
            raise RakitError(
                code=ErrorCode.CONFIG_INVALID_RESOURCE_POLICY,
                message="Invalid resource write policy declaration",
                status_code=500,
                details={"resource_id": resource_id, "reason": "duplicate_write_policy"},
            )
        known_fields = set(self._resource_services[resource_id].data_source.fields)
        writable = {field.field_id for field in binding.form_schema.fields if field.writable}
        if not writable or not writable <= known_fields:
            raise RakitError(
                code=ErrorCode.CONFIG_INVALID_RESOURCE_POLICY,
                message="Invalid resource write policy declaration",
                status_code=500,
                details={"resource_id": resource_id, "reason": "unknown_or_empty_writable_field"},
            )
        self._write_resource_bindings[resource_id] = replace(binding, resource_id=resource_id)
        for route_name, methods, path in (
            (f"resource:{resource_id}:create", ("GET",), binding.create_path),
            (f"resource:{resource_id}:create.submit", ("POST",), binding.create_path),
            (f"resource:{resource_id}:edit", ("GET",), binding.update_path),
            (f"resource:{resource_id}:edit.submit", ("POST",), binding.update_path),
            (f"resource:{resource_id}:delete", ("GET",), binding.delete_path),
            (f"resource:{resource_id}:delete.submit", ("POST",), binding.delete_path),
        ):
            self._builder.add_route(
                RouteDefinition(
                    route_name=route_name,
                    methods=methods,
                    path=path,
                    owner_id=resource_id,
                )
            )

    def compile(self) -> CompiledApplication:
        if self.compiled is None:
            self.compiled = compile_application(self._builder)
            self._compiled_registry = self._builder.registry
        return self.compiled

    def _action_bindings(
        self,
        *,
        templates: Jinja2Templates,
        codec: IdentityCodec,
        verify_csrf: Callable[[Request], Awaitable[bool]],
        issue_submission_token: Callable[[Request], str],
        verify_submission_token: Callable[[Request], Awaitable[bool]],
        token_service: TokenService,
        operation_scope: Callable[[], AbstractAsyncContextManager[ServiceResolver]],
        unit_of_work_factory: Callable[[], OperationUnitOfWorkFactory | None],
    ) -> tuple[ActionBinding, ...]:
        """Materialize the compiled action routes as web bindings.

        Pairs are grouped by declared owner: RECORD/RESOURCE actions use the
        owning resource's canonical scoped ``ResourceService`` as the record
        loader, and PAGE actions share one binding. Authorization always
        evaluates the exact compiler-resolved permission. Requires auth,
        CSRF/submission plumbing, and the fail-closed capability checks to
        have run before this is called.
        """
        assert self.compiled is not None

        async def authorize_action(
            request: Request,
            compiled_action: CompiledActionDefinition,
            identity: RecordIdentity | None,
        ) -> OperationAuthorization | None:
            principal = request.scope.get("state", {}).get("principal")
            if principal is None or not principal.authenticated:
                return None
            if not compiled_action.permission.matches(
                principal, superuser_bypass=self._superuser_bypass
            ):
                return None
            assert principal.subject_id is not None
            definition = compiled_action.definition
            owner_id = (
                definition.page_id
                if definition.scope is ActionScope.PAGE
                else definition.resource_id
            )
            assert owner_id is not None
            return OperationAuthorization.for_requirement(
                admin_id=self.config.admin_id,
                resource_id=owner_id,
                operation=f"action:{definition.action_id}",
                principal_id=principal.subject_id,
                requirement=compiled_action.permission,
                target_identity=identity,
            )

        idempotency_store = self._operation_idempotency_store
        bindings: list[ActionBinding] = []
        for resource_id, service in self._resource_services.items():
            pairs = tuple(
                (route, compiled)
                for route, compiled in self.compiled.action_routes
                if compiled.definition.scope in (ActionScope.RECORD, ActionScope.RESOURCE)
                and compiled.definition.resource_id == resource_id
            )
            if not pairs:
                continue
            provider = self._concurrency_providers.get(resource_id)

            async def load_record(
                identity: RecordIdentity, service: ResourceService = service
            ) -> object | None:
                try:
                    return await service.detail(identity)
                except RakitError as exc:
                    if exc.code is ErrorCode.RESOURCE_NOT_FOUND:
                        return None
                    raise

            bindings.append(
                ActionBinding(
                    routes=pairs,
                    templates=templates,
                    codec=codec,
                    verify_csrf=verify_csrf,
                    verify_submission_token=verify_submission_token,
                    issue_submission_token=issue_submission_token,
                    authorize_action=authorize_action,
                    load_record=load_record,
                    concurrency=(
                        ConcurrencyTokenService(token_service) if provider is not None else None
                    ),
                    concurrency_resource_id=resource_id if provider is not None else None,
                    record_version=(provider.version_for if provider is not None else None),
                    token_service=token_service,
                    idempotency_store=idempotency_store,
                    deadline_seconds=self._mutation_deadline_seconds,
                    operation_scope=operation_scope,
                    unit_of_work_factory=unit_of_work_factory,
                    advanced_response_adapter=self._advanced_action_response_adapter,
                    label=self.config.title,
                )
            )
        page_pairs = tuple(
            (route, compiled)
            for route, compiled in self.compiled.action_routes
            if compiled.definition.scope is ActionScope.PAGE
        )
        if page_pairs:
            bindings.append(
                ActionBinding(
                    routes=page_pairs,
                    templates=templates,
                    codec=codec,
                    verify_csrf=verify_csrf,
                    verify_submission_token=verify_submission_token,
                    issue_submission_token=issue_submission_token,
                    authorize_action=authorize_action,
                    token_service=token_service,
                    idempotency_store=idempotency_store,
                    deadline_seconds=self._mutation_deadline_seconds,
                    operation_scope=operation_scope,
                    unit_of_work_factory=unit_of_work_factory,
                    advanced_response_adapter=self._advanced_action_response_adapter,
                    label=self.config.title,
                )
            )
        return tuple(bindings)

    async def _open_application_resolver(self) -> None:
        assert self._compiled_registry is not None
        self._application_resolver = self._compiled_registry.application_scope()
        await self._application_resolver.__aenter__()

    async def _close_application_resolver(self) -> None:
        resolver, self._application_resolver = self._application_resolver, None
        if resolver is not None:
            await resolver.__aexit__(None, None, None)

    def asgi(self) -> ASGIApp:
        self.compile()
        assert self.compiled is not None
        compiled_app = self.compiled

        async def home(_request: Request) -> PlainTextResponse:
            return PlainTextResponse(self.config.title)

        async def health(_request: Request) -> JSONResponse:
            if await self.lifecycle.check_health():
                return JSONResponse({"status": "ok"})
            return JSONResponse({"status": "unhealthy"}, status_code=503)

        async def ready(_request: Request) -> JSONResponse:
            if await self.lifecycle.check_ready():
                return JSONResponse({"status": "ready"})
            return JSONResponse({"status": "not_ready"}, status_code=503)

        async def rakit_error_handler(_request: Request, exc: Exception) -> JSONResponse:
            # Minimal error-to-HTTP translation: a RakitError already carries the
            # HTTP status it intends (e.g. RESOURCE_NOT_FOUND -> 404), so honour it
            # rather than letting it surface as an unhandled 500.
            assert isinstance(exc, RakitError)
            return JSONResponse(
                exc.to_public_dict(),
                status_code=exc.status_code,
                headers={"Cache-Control": "no-store"},
            )

        @asynccontextmanager
        async def lifespan(_app: Starlette) -> AsyncIterator[None]:
            configure_logging(debug=self.config.debug)
            await self._open_application_resolver()
            try:
                await self.lifecycle.run_startup()
                try:
                    yield
                finally:
                    await self.lifecycle.run_shutdown()
            finally:
                await self._close_application_resolver()

        templates = build_templates(self._template_dirs)
        bindings: dict[str, ResourceBinding] = {}
        resource_routes: list[Route] = []
        for resource_id, service in self._resource_services.items():
            binding = ResourceBinding(
                definition=self._resource_definitions[resource_id],
                service=service,
                templates=templates,
            )
            bindings[resource_id] = binding
            resource_routes.extend(build_resource_routes(binding))

        generated_rest_routes: list[Route] = []
        api_by_resource = {api.resource_id: api for api in self.compiled.compiled_resource_apis}
        for resource_id, api in api_by_resource.items():
            generated_rest_routes.extend(
                build_generated_rest_routes(
                    GeneratedRestBinding(
                        api=api,
                        definition=self._resource_definitions[resource_id],
                        service=self._resource_services[resource_id],
                        schema_adapter=self._schema_adapter,
                        admin_id=self.config.admin_id,
                        auth_enabled=(
                            self._auth_backend is not None and self._session_store is not None
                        ),
                        superuser_bypass=self._superuser_bypass,
                    )
                )
            )

        write_routes: list[Route] = []
        action_routes: list[Route] = []
        page_routes: list[Route] = []
        uow_factory_registered = (
            ServiceKey(OperationUnitOfWorkFactory, None) in self._compiled_registry.providers
            if self._compiled_registry is not None
            else False
        )
        validate_page_runtime(
            self.compiled,
            auth_enabled=self._auth_backend is not None and self._session_store is not None,
            idempotency_store=self._operation_idempotency_store,
            uow_factory_registered=uow_factory_registered,
            debug=self.config.debug,
        )

        if self.compiled.action_routes:
            if self._auth_backend is None or self._session_store is None:
                raise RakitError(
                    code=ErrorCode.CONFIG_INVALID,
                    message="Compiled actions require configured authentication.",
                    status_code=500,
                )
            if self.config.security.secret_key is None:
                raise RakitError(
                    code=ErrorCode.CONFIG_INVALID,
                    message=(
                        "A security.secret_key is required to serve compiled actions "
                        "(it derives the CSRF and submission-token signing key)."
                    ),
                    status_code=500,
                )
            missing_providers = sorted(
                (
                    f"{compiled.definition.action_id} (resource {compiled.definition.resource_id})"
                    for _, compiled in self.compiled.action_routes
                    if compiled.definition.requires_concurrency
                    and compiled.definition.resource_id not in self._concurrency_providers
                )
            )
            if missing_providers:
                raise RakitError(
                    code=ErrorCode.CONFIG_INVALID,
                    message=(
                        "Compiled RECORD actions require a registered concurrency "
                        "provider for their resource: " + ", ".join(missing_providers)
                    ),
                    status_code=500,
                )
            for _, compiled in self.compiled.action_routes:
                action = compiled.definition
                owner = (
                    action.resource_id if action.scope is not ActionScope.PAGE else action.page_id
                )
                capabilities = resolve_operation_executor_capabilities(action.executor)
                if action.mutating and action.transaction_policy in (
                    TransactionPolicy.AUTO,
                    TransactionPolicy.MANUAL,
                ):
                    if not capabilities.participates_in_uow:
                        raise RakitError(
                            code=ErrorCode.CONFIG_INVALID,
                            message=(
                                f'Action "{action.action_id}" ({action.scope.value}, owner '
                                f'"{owner}") declares {action.transaction_policy.value} '
                                "transaction policy but its executor does not participate "
                                "in the operation unit of work."
                            ),
                            status_code=500,
                            details={
                                "action_id": action.action_id,
                                "owner": owner,
                                "transaction_policy": str(action.transaction_policy),
                                "reason": "executor_not_uow_managed",
                            },
                        )
                    if not uow_factory_registered:
                        raise RakitError(
                            code=ErrorCode.CONFIG_INVALID,
                            message=(
                                f'Action "{action.action_id}" ({action.scope.value}, owner '
                                f'"{owner}") requires a registered operation unit-of-work '
                                "provider (install a persistence plugin such as "
                                "SQLAlchemyPlugin)."
                            ),
                            status_code=500,
                            details={
                                "action_id": action.action_id,
                                "owner": owner,
                                "transaction_policy": str(action.transaction_policy),
                                "reason": "operation_uow_not_configured",
                            },
                        )
                if action.requires_concurrency:
                    if not (
                        action.mutating and action.transaction_policy is TransactionPolicy.AUTO
                    ):
                        raise RakitError(
                            code=ErrorCode.CONFIG_INVALID,
                            message=(
                                f'Action "{action.action_id}" requires strong concurrency, '
                                "which needs a mutating operation with an automatic "
                                "transaction policy."
                            ),
                            status_code=500,
                            details={
                                "action_id": action.action_id,
                                "owner": owner,
                                "transaction_policy": str(action.transaction_policy),
                                "reason": "invalid_concurrency_transaction_policy",
                            },
                        )
                    if not capabilities.atomic_concurrency:
                        raise RakitError(
                            code=ErrorCode.CONFIG_INVALID,
                            message=(
                                f'Action "{action.action_id}" requires strong concurrency, '
                                "but its executor does not provide atomic concurrency."
                            ),
                            status_code=500,
                            details={
                                "action_id": action.action_id,
                                "owner": owner,
                                "transaction_policy": str(action.transaction_policy),
                                "reason": "atomic_concurrency_not_supported",
                            },
                        )
            if self._operation_idempotency_store is None:
                raise RakitError(
                    code=ErrorCode.CONFIG_INVALID,
                    message=(
                        "Compiled actions require an operation idempotency store "
                        "(Admin(operation_idempotency_store=...))."
                    ),
                    status_code=500,
                )
            validate_idempotency_store_for_production(
                self._operation_idempotency_store, debug=self.config.debug
            )

        exact_requirements = {
            route.path: compiled.permission for route, compiled in self.compiled.action_routes
        }
        exact_requirements.update(page_requirement_map(self.compiled))
        requirement_resolver = build_requirement_resolver(
            admin_id=self.config.admin_id,
            resource_paths={
                definition.path: resource_id
                for resource_id, definition in self._resource_definitions.items()
            },
            writable_resources=frozenset(self._write_resource_bindings),
            action_requirements=exact_requirements,
            generated_api_requirements=generated_rest_requirement_map(
                self.compiled.compiled_resource_apis,
                admin_id=self.config.admin_id,
            ),
        )
        if self._session_store is not None and self.config.security.secret_key is not None:
            write_token_service = TokenService.single_key(
                key_id="primary",
                value=self.config.security.secret_key,
                admin_id=self.config.admin_id,
            )
            write_csrf_service = CsrfService(write_token_service)

            async def authorize_write(request: Request) -> bool:
                principal = request.scope.get("state", {}).get("principal")
                requirement = requirement_resolver(
                    request.url.path.removeprefix(request.scope.get("root_path", "")),
                    request.method,
                )
                return bool(
                    principal is not None
                    and principal.authenticated
                    and requirement is not None
                    and requirement.matches(principal, superuser_bypass=self._superuser_bypass)
                )

            async def authorize_mutation(
                request: Request,
                operation: MutationOperation,
                identity: RecordIdentity | None,
            ) -> MutationAuthorization | None:
                principal = request.scope.get("state", {}).get("principal")
                requirement = requirement_resolver(
                    request.url.path.removeprefix(request.scope.get("root_path", "")),
                    request.method,
                )
                if (
                    principal is None
                    or not principal.authenticated
                    or requirement is None
                    or not requirement.matches(principal, superuser_bypass=self._superuser_bypass)
                ):
                    return None
                path = request.url.path.removeprefix(request.scope.get("root_path", ""))
                resource_id = next(
                    (
                        candidate_id
                        for candidate_path, candidate_id in (
                            (definition.path, candidate_id)
                            for candidate_id, definition in self._resource_definitions.items()
                        )
                        if path == candidate_path or path.startswith(f"{candidate_path}/")
                    ),
                    None,
                )
                if resource_id is None:
                    return None
                return MutationAuthorization(
                    admin_id=self.config.admin_id,
                    resource_id=resource_id,
                    operation=operation,
                    principal_id=principal.subject_id,
                    permissions=requirement.permissions,
                )

            async def authorize_graph_mutation(
                request: Request,
                root: MutationAuthorization,
                parent_identity: RecordIdentity | None,
                changes: tuple[object, ...],
            ) -> OperationAuthorizationSet | None:
                principal = request.scope.get("state", {}).get("principal")
                if principal is None or not principal.authenticated:
                    return None
                capabilities: list[OperationAuthorization] = []
                relationship_by_id = {
                    (entry.source_resource_id, str(entry.definition.relationship_id)): entry
                    for entry in compiled_app.relationships
                }
                for raw_change in changes:
                    if not isinstance(raw_change, RelationshipChangePlan):
                        return None
                    entry = relationship_by_id.get((root.resource_id, raw_change.relationship_id))
                    if entry is None or not entry.mutation_permission.matches(
                        principal, superuser_bypass=self._superuser_bypass
                    ):
                        return None
                    capabilities.append(
                        OperationAuthorization.for_requirement(
                            admin_id=self.config.admin_id,
                            resource_id=entry.source_resource_id,
                            operation=raw_change.operation_id,
                            principal_id=principal.subject_id,
                            requirement=entry.mutation_permission,
                            target_identity=parent_identity,
                        )
                    )
                    target_resource_id = str(
                        entry.definition.association_target_resource_id
                        or entry.definition.target_resource_id
                    )
                    for step in raw_change.steps:
                        requirement = None
                        identity = None
                        operation = None
                        if isinstance(step, CreateRelated):
                            requirement, operation = entry.target_create_permission, "target-create"
                        elif isinstance(step, UpdateRelated):
                            requirement, identity, operation = (
                                entry.target_update_permission,
                                step.identity,
                                "target-update",
                            )
                        elif isinstance(step, DeleteRelated):
                            requirement, identity, operation = (
                                entry.target_delete_permission,
                                step.identity,
                                "target-delete",
                            )
                        if requirement is not None:
                            if not requirement.matches(
                                principal, superuser_bypass=self._superuser_bypass
                            ):
                                return None
                            capabilities.append(
                                OperationAuthorization.for_requirement(
                                    admin_id=self.config.admin_id,
                                    resource_id=target_resource_id,
                                    operation=f"{raw_change.operation_id}:{operation}",
                                    principal_id=principal.subject_id,
                                    requirement=requirement,
                                    target_identity=identity,
                                )
                            )
                return OperationAuthorizationSet(root=root, capabilities=tuple(capabilities))

            async def authorize_relationship_editor(
                request: Request,
                relationship_id: str,
                parent_identity: RecordIdentity | None,
            ) -> bool:
                """Authorize relationship helper reads with the exact compiled requirement."""

                principal = request.scope.get("state", {}).get("principal")
                if principal is None or not principal.authenticated:
                    return False
                path = request.url.path.removeprefix(request.scope.get("root_path", ""))
                resource_id = next(
                    (
                        candidate_id
                        for candidate_path, candidate_id in (
                            (definition.path, candidate_id)
                            for candidate_id, definition in self._resource_definitions.items()
                        )
                        if path == candidate_path or path.startswith(f"{candidate_path}/")
                    ),
                    None,
                )
                if resource_id is None:
                    return False
                entry = next(
                    (
                        candidate
                        for candidate in compiled_app.relationships
                        if candidate.source_resource_id == resource_id
                        and str(candidate.definition.relationship_id) == relationship_id
                    ),
                    None,
                )
                return bool(
                    entry is not None
                    and entry.definition.effective_writable
                    and entry.mutation_permission.matches(
                        principal, superuser_bypass=self._superuser_bypass
                    )
                )

            async def verify_write_csrf(request: Request) -> bool:
                session_id = request.scope.get("state", {}).get("session_id")
                return isinstance(session_id, str) and await _verify_csrf(
                    request, write_csrf_service, session_id=session_id
                )

            def issue_submission_token(request: Request) -> str:
                session_id = request.scope.get("state", {}).get("session_id")
                if not isinstance(session_id, str):
                    return ""
                return write_token_service.issue_in(
                    "form_submission",
                    {"session_id": session_id, "path": request.scope.get("path", "")},
                    timedelta(minutes=15),
                )

            async def verify_submission_token(request: Request) -> bool:
                form = await request.form()
                tokens = form.getlist("submission_token")
                session_id = request.scope.get("state", {}).get("session_id")
                if (
                    len(tokens) != 1
                    or not isinstance(tokens[0], str)
                    or not isinstance(session_id, str)
                ):
                    return False
                try:
                    claims = write_token_service.verify(
                        tokens[0], expected_purpose="form_submission"
                    )
                except ValueError:
                    return False
                return claims.get("session_id") == session_id and claims.get(
                    "path"
                ) == request.scope.get("path", "")

            @asynccontextmanager
            async def operation_scope() -> AsyncIterator[ServiceResolver]:
                if self._application_resolver is None:
                    raise RuntimeError("Application services are not available")
                async with (
                    self._application_resolver.request_scope() as request_services,
                    request_services.operation_scope() as operation_services,
                ):
                    yield operation_services

            def action_uow_factory() -> OperationUnitOfWorkFactory | None:
                if self._application_resolver is None:
                    return None
                return self._application_resolver.require(OperationUnitOfWorkFactory)

            for write_binding in self._write_resource_bindings.values():
                secured_binding = replace(
                    write_binding,
                    authorize=authorize_write,
                    verify_csrf=verify_write_csrf,
                    verify_submission_token=verify_submission_token,
                    issue_submission_token=issue_submission_token,
                    mutation_authorizer=authorize_mutation,
                    graph_mutation_authorizer=authorize_graph_mutation,
                    relationship_editor_authorizer=authorize_relationship_editor,
                    templates=templates,
                    deadline_seconds=self._mutation_deadline_seconds,
                    operation_scope=operation_scope,
                )
                write_routes.extend(build_write_routes(secured_binding))
                if secured_binding.relationship_form is not None:
                    relationship_routes = build_relationship_routes(
                        secured_binding, secured_binding.relationship_form
                    )
                    write_routes.extend(relationship_routes)

            if self.compiled.compiled_pages:
                page_routes = build_admin_page_routes(
                    compiled=self.compiled,
                    templates=templates,
                    schema_adapter=self._schema_adapter,
                    admin_id=self.config.admin_id,
                    superuser_bypass=self._superuser_bypass,
                    verify_csrf=verify_write_csrf,
                    verify_submission_token=verify_submission_token,
                    issue_submission_token=issue_submission_token,
                    idempotency_store=self._operation_idempotency_store,
                    deadline_seconds=self._mutation_deadline_seconds,
                    operation_scope=operation_scope,
                    unit_of_work_factory=action_uow_factory,
                    label=self.config.title,
                )

            action_routes = []
            if self.compiled.action_routes:
                for action_binding in self._action_bindings(
                    templates=templates,
                    codec=IdentityCodec(),
                    verify_csrf=verify_write_csrf,
                    issue_submission_token=issue_submission_token,
                    verify_submission_token=verify_submission_token,
                    token_service=write_token_service,
                    operation_scope=operation_scope,
                    unit_of_work_factory=action_uow_factory,
                ):
                    action_routes.extend(build_action_routes(action_binding))
                assert self._operation_idempotency_store is not None
                action_routes.extend(
                    build_admin_bulk_action_routes(
                        compiled=self.compiled,
                        resource_services=self._resource_services,
                        concurrency_providers=self._concurrency_providers,
                        templates=templates,
                        verify_csrf=verify_write_csrf,
                        verify_submission_token=verify_submission_token,
                        issue_submission_token=issue_submission_token,
                        token_service=write_token_service,
                        idempotency_store=self._operation_idempotency_store,
                        admin_id=self.config.admin_id,
                        superuser_bypass=self._superuser_bypass,
                        deadline_seconds=self._mutation_deadline_seconds,
                        operation_scope=operation_scope,
                        unit_of_work_factory=action_uow_factory,
                        label=self.config.title,
                    )
                )

        app = Starlette(
            debug=self.config.debug,
            routes=[Route("/", home)],
            lifespan=lifespan,
            exception_handlers={RakitError: rakit_error_handler},
        )
        app.routes.append(Route("/_system/health", health))
        app.routes.append(Route("/_system/ready", ready))
        app.routes.append(Mount("/_system/static", app=static_files(), name="rakit-static"))
        for route in write_routes:
            app.routes.append(route)
        for route in resource_routes:
            app.routes.append(route)
        for route in generated_rest_routes:
            app.routes.append(route)
        for route in page_routes:
            app.routes.append(route)
        if self._auth_backend is not None and self._session_store is not None:
            if self.config.security.secret_key is None:
                raise RakitError(
                    code=ErrorCode.CONFIG_INVALID,
                    message=(
                        "A security.secret_key is required to enable authentication "
                        "(it derives the CSRF/session token signing key)."
                    ),
                    status_code=500,
                )
            token_service = TokenService.single_key(
                key_id="primary",
                value=self.config.security.secret_key,
                admin_id=self.config.admin_id,
            )
            csrf_service = CsrfService(token_service)
            auth_routes = build_auth_routes(
                auth_backend=self._auth_backend,
                session_store=self._session_store,
                csrf_service=csrf_service,
                rate_limiter=self._login_rate_limiter,
                templates=templates,
                admin_id=self.config.admin_id,
                secure_cookies=not self.config.debug,
                trusted_proxies=self._trusted_proxy_networks,
            )
            for route in auth_routes:
                app.routes.append(route)
        for route in action_routes:
            app.routes.append(route)
        app.state.rakit = SimpleNamespace(resources=bindings)

        # Authentication/authorization wrap the routed app *inside* the
        # security and request-context layers, so a rejection still gets
        # security headers and request-scoped logging, and so
        # PrincipalMiddleware runs before AuthorizationMiddleware reads the
        # principal it resolved.
        inner_app: ASGIApp = app
        if self._auth_backend is not None and self._session_store is not None:
            inner_app = AuthorizationMiddleware(
                inner_app,
                requirement_for=requirement_resolver,
                superuser_bypass=self._superuser_bypass,
            )
            inner_app = PrincipalMiddleware(
                inner_app,
                auth_backend=self._auth_backend,
                session_store=self._session_store,
            )

        secured_app = SecurityMiddleware(
            inner_app,
            allowed_hosts=self.config.security.allowed_hosts,
            content_security_policy_enabled=self.config.security.content_security_policy_enabled,
        )
        return RequestContextMiddleware(secured_app, admin_id=self.config.admin_id)
