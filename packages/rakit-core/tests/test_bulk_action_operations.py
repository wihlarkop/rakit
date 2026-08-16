"""Bulk action compiler and transaction contracts."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import cast

import pytest
from rakit_core.actions import (
    ActionContext,
    ActionDefinition,
    ActionRejected,
    ActionScope,
    ActionSuccess,
    DomainActionExecutor,
    PreparedMutationExecutor,
    action_permission_requirement,
)
from rakit_core.bulk import (
    BulkExecutionPolicy,
    BulkItemStatus,
    BulkPolicy,
    BulkSelection,
    BulkTarget,
)
from rakit_core.bulk_actions import build_atomic_bulk_operation_plan
from rakit_core.compiler import ApplicationBuilder, compile_application
from rakit_core.datasource import DataSourceCapabilities
from rakit_core.definitions import ResourceDefinition, ResourceFieldPolicy
from rakit_core.errors import RakitError
from rakit_core.events import EventPublisher
from rakit_core.identity import RecordIdentity
from rakit_core.mutations import OperationAuthorization
from rakit_core.operations import CancellationContext, OperationContext, run_operation_plan
from rakit_core.permissions import PermissionRequirement
from rakit_core.query import PageResult, ResourceQuery
from rakit_core.transactions import OperationUnitOfWorkFactory, TransactionPolicy


class _DataSource:
    capabilities = DataSourceCapabilities(read=True)
    fields = ("id", "name")
    identity_fields = ("id",)

    async def list(self, query: ResourceQuery) -> PageResult:
        raise AssertionError(query)

    async def count(self, query: ResourceQuery) -> int:
        raise AssertionError(query)

    async def detail(self, identity: RecordIdentity) -> object:
        raise AssertionError(identity)


class _TrackingUnitOfWork:
    def __init__(self, policy: TransactionPolicy) -> None:
        self.policy = policy
        self.marked_success = False
        self.committed = False
        self.rolled_back = False

    async def mark_success(self) -> None:
        self.marked_success = True

    async def commit(self) -> None:
        self.committed = True

    async def rollback(self, cause: BaseException | None = None) -> None:
        del cause
        self.rolled_back = True


class _TrackingUnitOfWorkFactory:
    def __init__(self) -> None:
        self.uow: _TrackingUnitOfWork | None = None

    @asynccontextmanager
    async def open(
        self,
        *,
        policy: TransactionPolicy,
        event_publisher: EventPublisher | None,
        operation_context: OperationContext,
    ) -> AsyncIterator[_TrackingUnitOfWork]:
        del event_publisher, operation_context
        uow = _TrackingUnitOfWork(policy)
        self.uow = uow
        try:
            yield uow
        except BaseException as exc:
            await uow.rollback(exc)
            raise
        else:
            if uow.marked_success:
                await uow.commit()
            else:
                await uow.rollback()


def _resource() -> ResourceDefinition:
    return ResourceDefinition(
        resource_id="orders",
        path="/orders",
        label="Orders",
        singular_label="Order",
        field_policy=ResourceFieldPolicy(
            list_fields=("id", "name"),
            detail_fields=("id", "name"),
        ),
    )


def _permission() -> PermissionRequirement:
    return action_permission_requirement("archive", admin_id="ops")


def _authorization(identity: RecordIdentity | None) -> OperationAuthorization:
    permission = _permission()
    return OperationAuthorization.for_requirement(
        admin_id="ops",
        resource_id="orders",
        operation="action:archive",
        principal_id="operator",
        requirement=permission,
        target_identity=identity,
    )


def _context(action: ActionDefinition, record_id: int) -> ActionContext:
    identity = RecordIdentity(values={"id": record_id})
    return ActionContext(
        definition=action,
        scope=ActionScope.BULK,
        identity=identity,
        record={"id": record_id},
        authorization=_authorization(identity),
    )


def _operation_context() -> OperationContext:
    authorization = _authorization(None)
    return OperationContext(
        deadline=None,
        cancellation=CancellationContext(),
        principal_id="operator",
        admin_id="ops",
        resource_id="orders",
        operation="action:archive",
        permissions=authorization.permissions,
        permission_requirement=authorization.requirement,
    )


def test_compiler_owns_bulk_action_route_and_pair() -> None:
    action = ActionDefinition(
        action_id="archive",
        label="Archive",
        scope=ActionScope.BULK,
        resource_id="orders",
        permission=_permission(),
        executor=DomainActionExecutor(lambda _context: ActionSuccess()),
        bulk_policy=BulkPolicy(require_concurrency_snapshot=False),
    )
    builder = ApplicationBuilder(admin_id="ops")
    builder.add_resource(_resource(), _DataSource())
    builder.add_action(action)

    compiled = compile_application(builder)

    route = next(route for route in compiled.routes if route.route_name.endswith("action:archive"))
    assert route.path == "/orders/_actions/archive"
    assert route.methods == ("GET", "POST")
    assert compiled.action_routes == ((route, compiled.compiled_actions[0]),)


def test_compiler_rejects_mutating_atomic_bulk_without_auto_transaction() -> None:
    action = ActionDefinition(
        action_id="archive",
        label="Archive",
        scope=ActionScope.BULK,
        resource_id="orders",
        permission=_permission(),
        executor=DomainActionExecutor(lambda _context: ActionSuccess()),
        mutating=True,
        transaction_policy=TransactionPolicy.DISABLED,
        bulk_policy=BulkPolicy(
            execution=BulkExecutionPolicy.ATOMIC,
            require_concurrency_snapshot=False,
        ),
    )
    builder = ApplicationBuilder(admin_id="ops")
    builder.add_resource(_resource(), _DataSource())
    builder.add_action(action)

    with pytest.raises(RakitError) as caught:
        compile_application(builder)

    assert caught.value.details["reason"] == "atomic_bulk_requires_auto"


def test_bulk_selection_requires_nonempty_unique_targets() -> None:
    first = BulkTarget(RecordIdentity(values={"id": 1}), {"id": 1})
    second = BulkTarget(RecordIdentity(values={"id": 2}), {"id": 2})
    selection = BulkSelection((first, second))
    assert selection.identities == (first.identity, second.identity)

    with pytest.raises(ValueError, match="at least one"):
        BulkSelection(())
    with pytest.raises(ValueError, match="unique"):
        BulkSelection((first, first))


@pytest.mark.anyio
async def test_atomic_bulk_commits_only_when_every_target_succeeds() -> None:
    committed_ids: list[int] = []

    def prepare(context: ActionContext) -> object:
        assert context.identity is not None
        return context.identity.values["id"]

    def commit(prepared: object, _context: ActionContext) -> ActionSuccess[None]:
        assert isinstance(prepared, int)
        committed_ids.append(prepared)
        return ActionSuccess()

    action = ActionDefinition(
        action_id="archive",
        label="Archive",
        scope=ActionScope.BULK,
        resource_id="orders",
        permission=_permission(),
        executor=PreparedMutationExecutor(prepare, commit),
        mutating=True,
        transaction_policy=TransactionPolicy.AUTO,
        bulk_policy=BulkPolicy(
            execution=BulkExecutionPolicy.ATOMIC,
            require_concurrency_snapshot=False,
        ),
    )
    plan = build_atomic_bulk_operation_plan(
        (_context(action, 1), _context(action, 2)),
        authorization=_authorization(None),
    )
    factory = _TrackingUnitOfWorkFactory()

    outcome = await run_operation_plan(
        plan,
        _operation_context(),
        unit_of_work_factory=cast(OperationUnitOfWorkFactory, factory),
    )

    assert committed_ids == [1, 2]
    assert outcome.succeeded_count == 2
    assert outcome.all_succeeded is True
    assert factory.uow is not None
    assert factory.uow.marked_success is True
    assert factory.uow.committed is True
    assert factory.uow.rolled_back is False


@pytest.mark.anyio
async def test_atomic_bulk_rejection_rolls_back_and_skips_remaining_targets() -> None:
    executed_ids: list[int] = []

    def prepare(context: ActionContext) -> object:
        assert context.identity is not None
        return context.identity.values["id"]

    def commit(prepared: object, _context: ActionContext):
        assert isinstance(prepared, int)
        executed_ids.append(prepared)
        if prepared == 2:
            return ActionRejected(errors={"status": "locked"}, message="Order is locked")
        return ActionSuccess()

    action = ActionDefinition(
        action_id="archive",
        label="Archive",
        scope=ActionScope.BULK,
        resource_id="orders",
        permission=_permission(),
        executor=PreparedMutationExecutor(prepare, commit),
        mutating=True,
        transaction_policy=TransactionPolicy.AUTO,
        bulk_policy=BulkPolicy(
            execution=BulkExecutionPolicy.ATOMIC,
            require_concurrency_snapshot=False,
        ),
    )
    plan = build_atomic_bulk_operation_plan(
        (_context(action, 1), _context(action, 2), _context(action, 3)),
        authorization=_authorization(None),
    )
    factory = _TrackingUnitOfWorkFactory()

    outcome = await run_operation_plan(
        plan,
        _operation_context(),
        unit_of_work_factory=cast(OperationUnitOfWorkFactory, factory),
    )

    assert executed_ids == [1, 2]
    assert [item.status for item in outcome.items] == [
        BulkItemStatus.SUCCEEDED,
        BulkItemStatus.REJECTED,
        BulkItemStatus.SKIPPED,
    ]
    assert outcome.all_succeeded is False
    assert factory.uow is not None
    assert factory.uow.marked_success is False
    assert factory.uow.committed is False
    assert factory.uow.rolled_back is True
