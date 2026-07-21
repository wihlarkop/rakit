from rakit_core.compiler import ApplicationBuilder, compile_application
from rakit_core.config import RakitConfig, SecretValue
from starlette.applications import Starlette
from starlette.responses import PlainTextResponse
from starlette.routing import Route


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

    def install(self, plugin) -> None:
        if self.compiled is not None:
            raise RuntimeError("Cannot install plugins after compilation")
        self.builder.install(plugin)

    def compile(self):
        if self.compiled is None:
            self.compiled = compile_application(self.builder)
        return self.compiled

    def asgi(self) -> Starlette:
        self.compile()

        async def home(_):
            return PlainTextResponse(self.config.title)

        return Starlette(debug=self.config.debug, routes=[Route("/", home)])
