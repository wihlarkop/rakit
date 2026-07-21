import httpx
import pytest
from rakit import Admin, SecretValue
from rakit_web.lifecycle import LifecycleManager, RuntimeState


@pytest.mark.anyio
async def test_health_and_readiness_are_minimal(client) -> None:
    health = await client.get("/_system/health")
    ready = await client.get("/_system/ready")
    assert health.json() == {"status": "ok"}
    assert ready.json() == {"status": "ready"}
    assert health.status_code == 200
    assert ready.status_code == 200


@pytest.mark.anyio
async def test_health_returns_200_before_lifespan_startup() -> None:
    # Health is process liveness only -- it must not depend on readiness
    # having been reached, and must never touch a registered check or a
    # database. Exercise this directly on a fresh (never-started)
    # LifecycleManager rather than through the full ASGI stack.
    manager = LifecycleManager()
    assert manager.state is RuntimeState.CREATED
    assert await manager.check_health() is True
    assert await manager.check_ready() is False


@pytest.mark.anyio
async def test_ready_endpoint_returns_503_via_admin_before_startup() -> None:
    admin = Admin(
        admin_id="operations",
        title="Operations",
        debug=False,
        secret_key=SecretValue("x" * 32),
    )
    app = admin.asgi()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as http_client:
        # No lifespan driven here on purpose: LifecycleManager never left
        # CREATED, so readiness must be 503 while health is still 200.
        health = await http_client.get("/_system/health")
        ready = await http_client.get("/_system/ready")
    assert health.status_code == 200
    assert health.json() == {"status": "ok"}
    assert ready.status_code == 503
    assert ready.json() == {"status": "not_ready"}


@pytest.mark.anyio
async def test_check_ready_false_when_critical_check_fails() -> None:
    manager = LifecycleManager()
    manager.state = RuntimeState.READY

    async def always_fails() -> bool:
        return False

    manager.register_health_check("db", always_fails, critical=True)

    assert await manager.check_ready() is False


@pytest.mark.anyio
async def test_check_ready_true_when_no_checks_registered_and_ready() -> None:
    manager = LifecycleManager()
    manager.state = RuntimeState.READY
    assert await manager.check_ready() is True


@pytest.mark.anyio
async def test_run_startup_reaches_ready() -> None:
    manager = LifecycleManager()
    await manager.run_startup()
    assert manager.state is RuntimeState.READY
    assert await manager.check_ready() is True


@pytest.mark.anyio
async def test_run_shutdown_ends_stopped_and_not_ready() -> None:
    manager = LifecycleManager()
    await manager.run_startup()
    assert await manager.check_ready() is True

    await manager.run_shutdown()

    assert manager.state is RuntimeState.STOPPED
    assert await manager.check_ready() is False


@pytest.mark.anyio
async def test_shutdown_marks_not_ready_before_owned_service_cleanup_runs() -> None:
    # Prove ordering: readiness must already be false (state has left READY)
    # by the time the owned-service cleanup hook runs, not after.
    events: list[str] = []

    async def on_stopping() -> None:
        events.append("cleanup_started")

    manager = LifecycleManager(on_stopping=on_stopping)
    await manager.run_startup()

    # Readiness is state-driven: the instant run_shutdown() flips state away
    # from READY (before awaiting the on_stopping hook), check_ready() must
    # already report False.
    original_on_stopping = manager._on_stopping
    assert original_on_stopping is not None

    async def wrapped_on_stopping() -> None:
        # By the time this hook (cleanup) runs, state must no longer be READY.
        assert manager.state is RuntimeState.STOPPING
        assert await manager.check_ready() is False
        events.append("ready_false_before_cleanup")
        await original_on_stopping()

    manager._on_stopping = wrapped_on_stopping

    await manager.run_shutdown()

    assert events == ["ready_false_before_cleanup", "cleanup_started"]
    assert manager.state is RuntimeState.STOPPED
