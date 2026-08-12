import anyio
import pytest
from rakit_core.auth import Principal
from rakit_core.di import ServiceRegistry, ServiceScope
from rakit_core.errors import ErrorCode, RakitError
from rakit_core.events import EventBus, EventPublisher
from rakit_core.operations import (
    CancellationContext,
    Deadline,
    OperationContext,
    activate_operation_context,
    current_operation_context,
    new_operation_id,
    run_with_deadline,
)


class _ApplicationProbe:
    pass


class _RequestProbe:
    pass


class _OperationProbe:
    pass


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


async def test_operation_context_carries_real_service_and_event_capabilities() -> None:
    principal = Principal(subject_id="user-1", authenticated=True, permissions=frozenset())
    registry = ServiceRegistry()
    mailer = object()
    registry.add_value(object, mailer, scope=ServiceScope.APPLICATION)
    publisher = EventPublisher(EventBus())
    async with (
        registry.application_scope() as application,
        application.request_scope() as request,
        request.operation_scope() as services,
    ):
        context = OperationContext(
            deadline=Deadline.after(30),
            cancellation=CancellationContext(),
            request_id="request-1",
            operation_id=new_operation_id(),
            principal=principal,
            services=services,
            events=publisher,
        )

        with activate_operation_context(context):
            assert current_operation_context() is context
        assert context.principal is principal
        assert context.request_id == "request-1"
        assert context.operation_id
        assert context.services is services
        assert context.services.require(object) is mailer
        assert context.events is publisher


@pytest.mark.anyio
async def test_operation_context_uses_real_di_scope_identity_and_cleanup() -> None:
    cleanup: list[str] = []
    registry = ServiceRegistry()
    application_probe = _ApplicationProbe()
    registry.add_value(_ApplicationProbe, application_probe, scope=ServiceScope.APPLICATION)
    registry.add_factory(
        _RequestProbe, lambda _resolver: _RequestProbe(), scope=ServiceScope.REQUEST
    )

    def make_operation(resolver):
        resolver.stack.callback(lambda: cleanup.append("operation"))
        return _OperationProbe()

    registry.add_factory(_OperationProbe, make_operation, scope=ServiceScope.OPERATION)
    async with registry.application_scope() as application, application.request_scope() as request:
        async with request.operation_scope() as first:
            context = OperationContext(
                deadline=Deadline.after(30),
                cancellation=CancellationContext(),
                services=first,
            )
            assert context.services is not None
            first_operation = context.services.require(_OperationProbe)
            assert context.services.require(_OperationProbe) is first_operation
            assert context.services.require(_RequestProbe) is request.require(_RequestProbe)
            assert context.services.require(_ApplicationProbe) is application_probe
        assert cleanup == ["operation"]
        async with request.operation_scope() as second:
            assert second.require(_OperationProbe) is not first_operation
            assert second.require(_RequestProbe) is request.require(_RequestProbe)
            assert second.require(_ApplicationProbe) is application_probe
    assert cleanup == ["operation", "operation"]
