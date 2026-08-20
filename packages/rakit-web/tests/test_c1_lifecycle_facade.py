import pytest
from rakit import Admin


@pytest.mark.anyio
async def test_admin_lifecycle_facade_preserves_startup_and_lifo_shutdown() -> None:
    admin = Admin(title="C1 lifecycle", debug=True)
    events: list[str] = []

    async def startup() -> None:
        events.append("startup")

    async def first_cleanup() -> None:
        events.append("first-cleanup")

    async def second_cleanup() -> None:
        events.append("second-cleanup")

    assert admin.on_startup(startup) is startup
    assert admin.on_shutdown(first_cleanup) is first_cleanup
    assert admin.on_shutdown(second_cleanup) is second_cleanup

    await admin.lifecycle.run_startup()
    await admin.lifecycle.run_shutdown()

    assert events == ["startup", "second-cleanup", "first-cleanup"]


@pytest.mark.anyio
async def test_admin_health_check_facade_preserves_readiness_semantics() -> None:
    admin = Admin(title="C1 health", debug=True)
    calls = 0

    async def database_ready() -> bool:
        nonlocal calls
        calls += 1
        return True

    admin.add_health_check(
        "database",
        database_ready,
        critical=True,
        timeout_seconds=1.0,
        cache_seconds=0.0,
    )

    assert await admin.lifecycle.check_ready() is False
    await admin.lifecycle.run_startup()
    assert await admin.lifecycle.check_ready() is True
    assert calls == 1
