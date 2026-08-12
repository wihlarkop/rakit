import anyio
import pytest
from rakit_core.auth import Principal
from rakit_core.errors import ErrorCode, RakitError
from rakit_core.operations import (
    CancellationContext,
    Deadline,
    OperationContext,
    activate_operation_context,
    current_operation_context,
    new_operation_id,
    run_with_deadline,
)


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


def test_operation_context_carries_immutable_request_metadata() -> None:
    principal = Principal(subject_id="user-1", authenticated=True, permissions=frozenset())
    context = OperationContext(
        deadline=Deadline.after(30),
        cancellation=CancellationContext(),
        request_id="request-1",
        operation_id=new_operation_id(),
        principal=principal,
        services={"mailer": object()},
        events="events",
    )

    with activate_operation_context(context):
        assert current_operation_context() is context
    assert context.principal is principal
    assert context.request_id == "request-1"
    assert context.operation_id
    assert context.services is not None
    assert "mailer" in context.services
    assert context.events == "events"
