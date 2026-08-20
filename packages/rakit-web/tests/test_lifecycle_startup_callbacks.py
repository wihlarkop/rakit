import pytest
from rakit_web.lifecycle import LifecycleManager, RuntimeState


@pytest.mark.anyio
async def test_starting_callbacks_run_in_registration_order_before_ready() -> None:
    lifecycle = LifecycleManager()
    observed: list[tuple[str, RuntimeState]] = []

    async def first() -> None:
        observed.append(("first", lifecycle.state))

    async def second() -> None:
        observed.append(("second", lifecycle.state))

    lifecycle.register_starting_callback(first)
    lifecycle.register_starting_callback(second)

    await lifecycle.run_startup()

    assert observed == [
        ("first", RuntimeState.STARTING),
        ("second", RuntimeState.STARTING),
    ]
    assert lifecycle.state is RuntimeState.READY


@pytest.mark.anyio
async def test_starting_callback_failure_marks_runtime_failed_and_propagates() -> None:
    lifecycle = LifecycleManager()

    async def broken() -> None:
        raise RuntimeError("bootstrap failed")

    lifecycle.register_starting_callback(broken)

    with pytest.raises(RuntimeError, match="bootstrap failed"):
        await lifecycle.run_startup()

    assert lifecycle.state is RuntimeState.FAILED
    assert await lifecycle.check_ready() is False
