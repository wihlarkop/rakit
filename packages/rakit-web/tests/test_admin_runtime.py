import httpx
import pytest
from conftest import LifespanDriver
from rakit import Admin, SecretValue
from rakit_core.compiler import ApplicationBuilder
from rakit_core.di import ServiceScope
from rakit_web.lifecycle import LifecycleManager


@pytest.mark.anyio
async def test_admin_root_responds() -> None:
    admin = Admin(
        admin_id="operations",
        title="Operations",
        debug=False,
        secret_key=SecretValue("x" * 32),
    )
    app = admin.asgi()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://localhost",
    ) as client:
        response = await client.get("/")
    assert response.status_code == 200
    assert response.text == "Operations"


@pytest.mark.anyio
async def test_application_resolver_closed_when_startup_fails(monkeypatch) -> None:
    # Regression test: _open_application_resolver() used to run before the
    # try/finally guarding shutdown, so a failure in run_startup() would
    # leak the resolver's AsyncExitStack (its registered cleanup callbacks
    # would never fire). The resolver must be closed even when startup
    # fails partway through.
    admin = Admin(
        admin_id="operations",
        title="Operations",
        debug=False,
        secret_key=SecretValue("x" * 32),
    )

    cleanup_calls: list[str] = []
    original_open = admin._open_application_resolver

    async def open_and_register_cleanup() -> None:
        await original_open()
        assert admin._application_resolver is not None

        async def on_cleanup() -> None:
            cleanup_calls.append("resolver_closed")

        admin._application_resolver.stack.push_async_callback(on_cleanup)

    monkeypatch.setattr(admin, "_open_application_resolver", open_and_register_cleanup)

    async def failing_run_startup(self) -> None:
        raise RuntimeError("boom: startup failed after resolver opened")

    monkeypatch.setattr(LifecycleManager, "run_startup", failing_run_startup)

    app = admin.asgi()
    driver = LifespanDriver(app)

    with pytest.raises(RuntimeError, match="boom: startup failed after resolver opened"):
        await driver.__aenter__()

    assert cleanup_calls == ["resolver_closed"]
    assert admin._application_resolver is None


@pytest.mark.anyio
async def test_application_resolver_detached_even_when_aexit_raises() -> None:
    # Regression test: _close_application_resolver() used to set
    # self._application_resolver = None only AFTER __aexit__() completed, so
    # a raising __aexit__() would leave a stale resolver reference (risking a
    # double-close). It must detach the reference before awaiting close.
    admin = Admin(
        admin_id="operations",
        title="Operations",
        debug=False,
        secret_key=SecretValue("x" * 32),
    )
    app = admin.asgi()
    driver = LifespanDriver(app)

    async with driver:
        assert admin._application_resolver is not None

        async def failing_cleanup() -> None:
            raise RuntimeError("boom: resolver cleanup failed")

        admin._application_resolver.stack.push_async_callback(failing_cleanup)

    # Shutdown failure policy is log-and-continue: the LifespanDriver's
    # __aexit__ must not raise, and the resolver reference must be detached
    # regardless of the cleanup callback's failure.
    assert admin._application_resolver is None


# --- Finding 1: builder is read-only; compiled registry is captured once ---


def test_admin_builder_rebinding_raises_attribute_error() -> None:
    admin = Admin(
        admin_id="operations",
        title="Operations",
        debug=False,
        secret_key=SecretValue("x" * 32),
    )
    with pytest.raises(AttributeError):
        admin.builder = ApplicationBuilder()  # type: ignore


def test_compiled_registry_is_same_object_as_builder_registry_after_compile() -> None:
    admin = Admin(
        admin_id="operations",
        title="Operations",
        debug=False,
        secret_key=SecretValue("x" * 32),
    )
    admin.compile()
    assert admin._compiled_registry is admin.builder.registry


class _ProbeService:
    def __init__(self) -> None:
        self.value = "probe-value"


class _ProbePlugin:
    plugin_id = "probe"

    def configure(self, builder: ApplicationBuilder) -> None:
        builder.registry.add_factory(
            _ProbeService, lambda _: _ProbeService(), scope=ServiceScope.APPLICATION
        )


@pytest.mark.anyio
async def test_lifespan_resolves_application_scoped_service_from_compiled_registry() -> None:
    # Proves _open_application_resolver() genuinely uses the registry that
    # was frozen at compile time, not a builder attribute reached at
    # runtime that could have been replaced after compilation.
    admin = Admin(
        admin_id="operations",
        title="Operations",
        debug=False,
        secret_key=SecretValue("x" * 32),
    )
    admin.install(_ProbePlugin())

    app = admin.asgi()
    driver = LifespanDriver(app)

    async with driver:
        assert admin._application_resolver is not None
        service = admin._application_resolver.require(_ProbeService)
        assert service.value == "probe-value"
