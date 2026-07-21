import httpx
import pytest
from conftest import LifespanDriver
from rakit import Admin, SecretValue
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
        base_url="http://testserver",
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
