"""Plan 05 Task 6 custom page execution and transaction contracts."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import pytest
from pydantic import BaseModel, ValidationError
from rakit_core.auth import Principal
from rakit_core.definitions import PageDefinition
from rakit_core.events import EventPublisher
from rakit_core.mutations import OperationAuthorization
from rakit_core.operations import CancellationContext, OperationContext, run_operation_plan
from rakit_core.pages import (
    DomainPageHandler,
    PageContext,
    PageRedirect,
    PageRejected,
    PageResult,
    PreparedPageMutationHandler,
    build_page_operation_plan,
)
from rakit_core.permissions import PermissionRequirement
from rakit_core.transactions import TransactionPolicy


class _Input(BaseModel):
    limit: int


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


def _permission() -> PermissionRequirement:
    return PermissionRequirement.all_of("ops.pages.report.view")


def _authorization() -> OperationAuthorization:
    return OperationAuthorization.for_requirement(
        admin_id="ops",
        resource_id="report",
        operation="page:report",
        principal_id="operator",
        requirement=_permission(),
    )


def _operation_context() -> OperationContext:
    authorization = _authorization()
    return OperationContext(
        deadline=None,
        cancellation=CancellationContext(),
        principal_id="operator",
        admin_id="ops",
        resource_id="report",
        operation="page:report",
        permissions=authorization.permissions,
        permission_requirement=authorization.requirement,
    )


def _context(definition: PageDefinition, *, limit: int = 5) -> PageContext:
    return PageContext(
        definition=definition,
        values=_Input(limit=limit),
        authorization=_authorization(),
        principal=Principal(subject_id="operator", authenticated=True),
    )


def test_page_result_contracts_are_explicit_and_redirects_are_internal() -> None:
    assert PageResult(payload={"count": 2}, message="Loaded").status_code == 200
    assert PageRejected(errors={"limit": "Too large"}).status_code == 409
    assert PageRedirect("/reports").location == "/reports"

    with pytest.raises(ValueError, match="2xx"):
        PageResult(status_code=302)
    with pytest.raises(ValueError, match="absolute"):
        PageRedirect("reports")
    with pytest.raises(ValueError, match="requires errors or a message"):
        PageRejected(errors={})


def test_page_definition_keeps_static_read_only_pages_and_rejects_dynamic_paths() -> None:
    static = PageDefinition(page_id="about", path="/about", label="About")
    assert static.handler is None

    with pytest.raises(ValidationError, match="path parameters"):
        PageDefinition(page_id="dynamic", path="/reports/{report_id}", label="Dynamic")


def test_mutating_page_requires_callable_handler() -> None:
    with pytest.raises(ValidationError, match="requires a callable handler"):
        PageDefinition(
            page_id="rebuild",
            path="/rebuild",
            label="Rebuild",
            mutating=True,
            transaction_policy=TransactionPolicy.AUTO,
        )


@pytest.mark.anyio
async def test_read_only_page_executes_typed_handler_without_uow() -> None:
    seen: list[int] = []

    async def handler(context: PageContext) -> PageResult[dict[str, int]]:
        assert isinstance(context.values, _Input)
        seen.append(context.values.limit)
        return PageResult(payload={"limit": context.values.limit})

    definition = PageDefinition(
        page_id="report",
        path="/reports",
        label="Report",
        input_schema=_Input,
        handler=DomainPageHandler(handler),
    )
    plan = build_page_operation_plan(_context(definition, limit=7))

    result = await run_operation_plan(plan, _operation_context(), unit_of_work_factory=None)

    assert isinstance(result, PageResult)
    assert result.payload == {"limit": 7}
    assert seen == [7]


@pytest.mark.anyio
async def test_mutating_page_redirect_commits_auto_uow() -> None:
    committed: list[int] = []

    def prepare(context: PageContext) -> object:
        assert isinstance(context.values, _Input)
        return context.values.limit

    def commit(prepared: object, _context: PageContext) -> PageRedirect:
        assert isinstance(prepared, int)
        committed.append(prepared)
        return PageRedirect("/reports", message="Rebuilt")

    definition = PageDefinition(
        page_id="report",
        path="/reports",
        label="Report",
        input_schema=_Input,
        handler=PreparedPageMutationHandler(prepare, commit),
        mutating=True,
        transaction_policy=TransactionPolicy.AUTO,
    )
    factory = _TrackingUnitOfWorkFactory()
    plan = build_page_operation_plan(_context(definition))

    result = await run_operation_plan(
        plan,
        _operation_context(),
        unit_of_work_factory=factory,
    )

    assert isinstance(result, PageRedirect)
    assert committed == [5]
    assert factory.uow is not None
    assert factory.uow.marked_success is True
    assert factory.uow.committed is True
    assert factory.uow.rolled_back is False


@pytest.mark.anyio
async def test_mutating_page_rejection_rolls_back_auto_uow() -> None:
    definition = PageDefinition(
        page_id="report",
        path="/reports",
        label="Report",
        input_schema=_Input,
        handler=PreparedPageMutationHandler(
            lambda context: context.values,
            lambda _prepared, _context: PageRejected(
                errors={"limit": "Not allowed"}, message="Rejected"
            ),
        ),
        mutating=True,
        transaction_policy=TransactionPolicy.AUTO,
    )
    factory = _TrackingUnitOfWorkFactory()

    result = await run_operation_plan(
        build_page_operation_plan(_context(definition)),
        _operation_context(),
        unit_of_work_factory=factory,
    )

    assert isinstance(result, PageRejected)
    assert factory.uow is not None
    assert factory.uow.marked_success is False
    assert factory.uow.committed is False
    assert factory.uow.rolled_back is True


@pytest.mark.anyio
async def test_mutating_rendered_result_never_commits_auto_uow() -> None:
    definition = PageDefinition(
        page_id="report",
        path="/reports",
        label="Report",
        input_schema=_Input,
        handler=PreparedPageMutationHandler(
            lambda context: context.values,
            lambda _prepared, _context: PageResult(payload={"unsafe": True}),
        ),
        mutating=True,
        transaction_policy=TransactionPolicy.AUTO,
    )
    factory = _TrackingUnitOfWorkFactory()

    result = await run_operation_plan(
        build_page_operation_plan(_context(definition)),
        _operation_context(),
        unit_of_work_factory=factory,
    )

    assert isinstance(result, PageResult)
    assert factory.uow is not None
    assert factory.uow.marked_success is False
    assert factory.uow.committed is False
    assert factory.uow.rolled_back is True
