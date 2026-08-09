import anyio
import pytest
from rakit_core.errors import ErrorCode, RakitError
from rakit_core.operations import CancellationContext, Deadline, run_with_deadline


@pytest.mark.anyio
async def test_expired_deadline_returns_a_stable_timeout_error() -> None:
    async def slow_operation() -> None:
        await anyio.sleep(0.02)

    with pytest.raises(RakitError) as caught:
        await run_with_deadline(slow_operation(), Deadline.after(0.001))
    assert caught.value.code == ErrorCode.OPERATION_TIMEOUT
    assert caught.value.status_code == 504


def test_cancellation_context_fails_before_mutation_checkpoint() -> None:
    context = CancellationContext()
    context.cancel()

    with pytest.raises(RakitError) as caught:
        context.check()
    assert caught.value.code == ErrorCode.OPERATION_TIMEOUT
