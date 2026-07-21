from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from rakit_core.compiler import ApplicationBuilder, compile_application
from rakit_core.config import RakitConfig, SecretValue
from rakit_core.di import ServiceResolver
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, PlainTextResponse
from starlette.routing import Route

from .lifecycle import LifecycleManager


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

    def asgi(self) -> Starlette:
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
            await self._open_application_resolver()
            await self.lifecycle.run_startup()
            try:
                yield
            finally:
                await self.lifecycle.run_shutdown()

        app = Starlette(debug=self.config.debug, routes=[Route("/", home)], lifespan=lifespan)
        app.routes.append(Route("/_system/health", health))
        app.routes.append(Route("/_system/ready", ready))
        return app
