import asyncio

import httpx
import pytest
from conftest import LifespanDriver
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


@pytest.mark.anyio
async def test_health_endpoint_returns_503_when_lifecycle_failed() -> None:
    admin = Admin(
        admin_id="operations",
        title="Operations",
        debug=False,
        secret_key=SecretValue("x" * 32),
    )
    app = admin.asgi()
    transport = httpx.ASGITransport(app=app)
    async with LifespanDriver(app):
        assert admin.lifecycle.state is RuntimeState.READY
        admin.lifecycle.state = RuntimeState.FAILED
        async with httpx.AsyncClient(
            transport=transport, base_url="http://testserver"
        ) as http_client:
            response = await http_client.get("/_system/health")
        assert response.status_code == 503
        assert response.json() == {"status": "unhealthy"}
        admin.lifecycle.state = RuntimeState.READY


@pytest.mark.anyio
async def test_health_endpoint_returns_200_when_lifecycle_healthy(client) -> None:
    response = await client.get("/_system/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


@pytest.mark.anyio
async def test_check_ready_runs_critical_checks_concurrently() -> None:
    # Deterministic proof that critical checks overlap in flight, rather than
    # running one at a time: both checks record that they started and then
    # block on a shared release event. If they ran sequentially, the second
    # check could not start until the first one returned -- but the first
    # one is deliberately blocked on the (not yet set) release event, so
    # both "started" events becoming set proves genuine concurrency.
    manager = LifecycleManager()
    started_order: list[str] = []
    check_a_started = asyncio.Event()
    check_b_started = asyncio.Event()
    release = asyncio.Event()

    async def check_a() -> bool:
        started_order.append("a")
        check_a_started.set()
        await release.wait()
        return True

    async def check_b() -> bool:
        started_order.append("b")
        check_b_started.set()
        await release.wait()
        return True

    manager.state = RuntimeState.READY
    manager.register_health_check("a", check_a, critical=True)
    manager.register_health_check("b", check_b, critical=True)

    task = asyncio.create_task(manager.check_ready())
    try:
        await asyncio.wait_for(
            asyncio.gather(check_a_started.wait(), check_b_started.wait()), timeout=1
        )
        assert set(started_order) == {"a", "b"}
        release.set()
        assert await asyncio.wait_for(task, timeout=1) is True
    finally:
        release.set()
        if not task.done():
            await asyncio.wait_for(task, timeout=1)


@pytest.mark.anyio
async def test_check_ready_bounds_concurrency_to_max_concurrent_checks() -> None:
    # Prove the semaphore genuinely serializes execution when the limit is
    # 1: check B must not start until check A has been released and has
    # completed.
    manager = LifecycleManager(max_concurrent_checks=1)
    check_a_started = asyncio.Event()
    check_b_started = asyncio.Event()
    release_a = asyncio.Event()

    async def check_a() -> bool:
        check_a_started.set()
        await release_a.wait()
        return True

    async def check_b() -> bool:
        check_b_started.set()
        return True

    manager.state = RuntimeState.READY
    manager.register_health_check("a", check_a, critical=True)
    manager.register_health_check("b", check_b, critical=True)

    task = asyncio.create_task(manager.check_ready())
    try:
        await asyncio.wait_for(check_a_started.wait(), timeout=1)

        # Check B must not have started yet -- it is blocked on the
        # semaphore held by check A.
        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(check_b_started.wait(), timeout=0.2)
        assert not check_b_started.is_set()

        release_a.set()

        await asyncio.wait_for(check_b_started.wait(), timeout=1)
        assert await asyncio.wait_for(task, timeout=1) is True
    finally:
        release_a.set()
        if not task.done():
            await asyncio.wait_for(task, timeout=1)


@pytest.mark.anyio
async def test_lifespan_driver_surfaces_startup_failure_promptly(monkeypatch) -> None:
    # If LifecycleManager.run_startup() raises, Starlette's Router.lifespan()
    # sends "lifespan.startup.failed" then re-raises inside the ASGI
    # callable's background task. LifespanDriver must not hang waiting for
    # "lifespan.startup.complete" that will never arrive -- it must wake up
    # and raise a clear error surfacing the real failure.
    async def failing_run_startup(self) -> None:
        raise RuntimeError("boom: plugin configure() failed")

    monkeypatch.setattr(LifecycleManager, "run_startup", failing_run_startup)

    admin = Admin(
        admin_id="operations",
        title="Operations",
        debug=False,
        secret_key=SecretValue("x" * 32),
    )
    app = admin.asgi()
    driver = LifespanDriver(app)

    with pytest.raises(RuntimeError, match="boom: plugin configure\\(\\) failed"):
        await asyncio.wait_for(driver.__aenter__(), timeout=5)
