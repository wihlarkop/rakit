import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace

import structlog
from rakit_core.admin_types import ModelAdmin, ResourceAdmin
from rakit_core.auth import AuthBackend, SessionStore
from rakit_core.compiler import ApplicationBuilder, CompiledApplication, Plugin, compile_application
from rakit_core.config import RakitConfig, SecretValue
from rakit_core.crypto import TokenService
from rakit_core.definitions import ResourceDefinition, ResourceFieldPolicy, RouteDefinition
from rakit_core.di import ServiceRegistry, ServiceResolver
from rakit_core.errors import ErrorCode, RakitError
from rakit_core.resources import ResourceService
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, PlainTextResponse
from starlette.routing import Mount, Route
from starlette.types import ASGIApp, Receive, Scope, Send

from .assets import static_files
from .auth_routes import build_auth_routes
from .lifecycle import LifecycleManager
from .logging import bind_request_context, configure_logging, reset_request_context
from .resource_routes import ResourceBinding, build_resource_routes, build_templates
from .security.csrf import CsrfService
from .security.middleware import SecurityMiddleware
from .security.rate_limit import LoginRateLimiter
from .security.validation import validate_production_config

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
        login_rate_limiter: LoginRateLimiter | None = None,
        allowed_hosts: tuple[str, ...] | None = None,
        content_security_policy_enabled: bool = True,
        trusted_proxies: tuple[str, ...] = (),
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
        validate_production_config(self.config)
        self._auth_backend = auth_backend
        self._session_store = session_store
        self._login_rate_limiter = login_rate_limiter or LoginRateLimiter()
        self._builder = ApplicationBuilder()
        self._builder.add_route(
            RouteDefinition(
                route_name="rakit.home",
                methods=("GET",),
                path="/",
                owner_id="rakit",
            )
        )
        self.compiled: CompiledApplication | None = None
        self._compiled_registry: ServiceRegistry | None = None
        self._application_resolver: ServiceResolver | None = None
        self._resource_services: dict[str, ResourceService] = {}
        self._resource_definitions: dict[str, ResourceDefinition] = {}
        self._template_dirs = template_dirs
        self.lifecycle = LifecycleManager()
        self.lifecycle.register_stopping_callback(self._close_application_resolver)

    @property
    def builder(self) -> ApplicationBuilder:
        return self._builder

    def install(self, plugin: Plugin) -> None:
        if self.compiled is not None:
            raise RuntimeError("Cannot install plugins after compilation")
        self._builder.install(plugin)

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
        )
        self._builder.add_resource(definition, data_source)
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

    def compile(self) -> CompiledApplication:
        if self.compiled is None:
            self.compiled = compile_application(self._builder)
            self._compiled_registry = self._builder.registry
        return self.compiled

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

        app = Starlette(
            debug=self.config.debug,
            routes=[Route("/", home)],
            lifespan=lifespan,
            exception_handlers={RakitError: rakit_error_handler},
        )
        app.routes.append(Route("/_system/health", health))
        app.routes.append(Route("/_system/ready", ready))
        app.routes.append(Mount("/_system/static", app=static_files(), name="rakit-static"))
        for route in resource_routes:
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
                trusted_proxies=self.config.security.trusted_proxies,
            )
            for route in auth_routes:
                app.routes.append(route)
        app.state.rakit = SimpleNamespace(resources=bindings)
        secured_app = SecurityMiddleware(
            app,
            allowed_hosts=self.config.security.allowed_hosts,
            content_security_policy_enabled=self.config.security.content_security_policy_enabled,
        )
        return RequestContextMiddleware(secured_app, admin_id=self.config.admin_id)
