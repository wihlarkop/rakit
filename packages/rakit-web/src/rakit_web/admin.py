import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import structlog
from rakit_core.compiler import ApplicationBuilder, compile_application
from rakit_core.config import RakitConfig, SecretValue
from rakit_core.di import ServiceResolver
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, PlainTextResponse
from starlette.routing import Route
from starlette.types import ASGIApp, Receive, Scope, Send

from .lifecycle import LifecycleManager
from .logging import bind_request_context, clear_request_context, configure_logging

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
        bind_request_context(request_id=request_id, admin_id=self.admin_id)
        try:
            logger.info("http.request.started", path=scope.get("path"))
            await self.app(scope, receive, send)
        finally:
            clear_request_context()


class Admin:
    def __init__(
        self,
        *,
        admin_id="admin",
        title: str,
        debug=False,
        secret_key: SecretValue | None = None,
    ) -> None:
        self.config = RakitConfig(
            admin_id=admin_id,
            title=title,
            debug=debug,
            security={"secret_key": secret_key},
        )
        self.builder = ApplicationBuilder()
        self.compiled = None
        self._application_resolver: ServiceResolver | None = None
        self.lifecycle = LifecycleManager(on_stopping=self._close_application_resolver)

    def install(self, plugin) -> None:
        if self.compiled is not None:
            raise RuntimeError("Cannot install plugins after compilation")
        self.builder.install(plugin)

    def compile(self):
        if self.compiled is None:
            self.compiled = compile_application(self.builder)
        return self.compiled

    async def _open_application_resolver(self) -> None:
        self._application_resolver = self.builder.registry.application_scope()
        await self._application_resolver.__aenter__()

    async def _close_application_resolver(self) -> None:
        if self._application_resolver is not None:
            await self._application_resolver.__aexit__(None, None, None)
            self._application_resolver = None

    def asgi(self) -> ASGIApp:
        self.compile()

        async def home(_):
            return PlainTextResponse(self.config.title)

        async def health(_request: Request) -> JSONResponse:
            return JSONResponse({"status": "ok"})

        async def ready(_request: Request) -> JSONResponse:
            if await self.lifecycle.check_ready():
                return JSONResponse({"status": "ready"})
            return JSONResponse({"status": "not_ready"}, status_code=503)

        @asynccontextmanager
        async def lifespan(_app: Starlette) -> AsyncIterator[None]:
            configure_logging(debug=self.config.debug)
            await self._open_application_resolver()
            await self.lifecycle.run_startup()
            try:
                yield
            finally:
                await self.lifecycle.run_shutdown()

        app = Starlette(debug=self.config.debug, routes=[Route("/", home)], lifespan=lifespan)
        app.routes.append(Route("/_system/health", health))
        app.routes.append(Route("/_system/ready", ready))
        return RequestContextMiddleware(app, admin_id=self.config.admin_id)
