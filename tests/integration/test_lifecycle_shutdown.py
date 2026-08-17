"""Shutdown/readiness release regressions."""

from __future__ import annotations

import asyncio

import pytest
from rakit_web.lifecycle import LifecycleManager, RuntimeState


@pytest.mark.anyio
async def test_readiness_flips_false_before_shutdown_cleanup_completes() -> None:
    manager = LifecycleManager()
    entered_cleanup = asyncio.Event()
    release_cleanup = asyncio.Event()

    async def cleanup() -> None:
        entered_cleanup.set()
        await release_cleanup.wait()

    manager.register_stopping_callback(cleanup)
    await manager.run_startup()
    assert manager.state is RuntimeState.READY
    assert await manager.check_ready() is True

    shutdown = asyncio.create_task(manager.run_shutdown())
    await entered_cleanup.wait()

    assert manager.state is RuntimeState.STOPPING
    assert await manager.check_ready() is False
    assert await manager.check_health() is True

    release_cleanup.set()
    await shutdown
    assert manager.state is RuntimeState.STOPPED
    assert await manager.check_ready() is False
    assert await manager.check_health() is False


@pytest.mark.anyio
async def test_shutdown_runs_all_cleanup_callbacks_even_when_one_fails() -> None:
    manager = LifecycleManager()
    calls: list[str] = []

    async def first() -> None:
        calls.append("first")

    async def broken() -> None:
        calls.append("broken")
        raise RuntimeError("cleanup failed")

    async def last() -> None:
        calls.append("last")

    manager.register_stopping_callback(first)
    manager.register_stopping_callback(broken)
    manager.register_stopping_callback(last)
    await manager.run_startup()
    await manager.run_shutdown()

    assert calls == ["last", "broken", "first"]
    assert manager.state is RuntimeState.STOPPED
