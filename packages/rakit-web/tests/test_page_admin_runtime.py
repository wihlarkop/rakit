"""Real Admin integration coverage for Plan 05 Task 6 pages."""

from datetime import UTC, datetime, timedelta

import httpx
import pytest
from conftest import LifespanDriver
from rakit import Admin, SecretValue
from rakit_core.actions import (
    ActionDefinition,
    ActionScope,
    ActionSuccess,
    DomainActionExecutor,
)
from rakit_core.auth import Principal, SessionRecord
from rakit_core.definitions import PageDefinition
from rakit_core.errors import ErrorCode, RakitError
from rakit_core.idempotency import IdempotencyReservation, IdempotencyStatus, OperationReceipt
from rakit_core.operations import current_operation_context
from rakit_core.pages import (
    DomainPageHandler,
    PageContext,
    PageRedirect,
    PageResult,
    PreparedPageMutationHandler,
)
from rakit_core.transactions import TransactionPolicy
from rakit_web.security.cookies import SESSION_COOKIE_NAME


class _AuthBackend:
    def __init__(self, permissions: frozenset[str]) -> None:
        self.permissions = permissions

    async def authenticate(self, identifier: str, password: str) -> Principal | None:
        del identifier, password
        return None

    async def resolve_principal(self, subject_id: str) -> Principal | None:
        if subject_id != "operator":
            return None
        return Principal(
            subject_id="operator",
            authenticated=True,
            permissions=self.permissions,
        )


class _SessionStore:
    production_safe = True

    def __init__(self) -> None:
        now = datetime.now(UTC)
        self.record = SessionRecord(
            session_id="session-1",
            subject_id="operator",
            created_at=now,
            last_seen_at=now,
            idle_expires_at=now + timedelta(hours=1),
            absolute_expires_at=now + timedelta(days=1),
        )

    async def create(self, principal: Principal) -> tuple[str, SessionRecord]:
        del principal
        return "token", self.record

    async def resolve(self, raw_token: str) -> SessionRecord | None:
        return self.record if raw_token == "token" else None

    async def rotate(self, session_id: str) -> tuple[str, SessionRecord]:
        del session_id
        return "token", self.record

    async def revoke(self, session_id: str) -> None:
        del session_id


class _Store:
    production_safe = True

    async def begin(self, token_hash: str, *, fingerprint: str) -> IdempotencyReservation:
        del token_hash, fingerprint
        return IdempotencyReservation(1, IdempotencyStatus.IN_PROGRESS)

    async def complete(
        self, reservation: IdempotencyReservation, receipt: OperationReceipt
    ) -> None:
        del reservation, receipt

    async def release(self, reservation: IdempotencyReservation) -> None:
        del reservation

    async def fail_final(self, reservation: IdempotencyReservation) -> None:
        del reservation


def _admin(
    permissions: frozenset[str],
    *,
    store: _Store | None = None,
) -> Admin:
    return Admin(
        admin_id="ops",
        title="Operations",
        debug=True,
        secret_key=SecretValue("x" * 32),
        auth_backend=_AuthBackend(permissions),
        session_store=_SessionStore(),
        operation_idempotency_store=store,
    )


def _client(admin: Admin) -> httpx.AsyncClient:
    client = httpx.AsyncClient(
        transport=httpx.ASGITransport(app=admin.asgi()),
        base_url="http://localhost",
    )
    client.cookies.set(SESSION_COOKIE_NAME, "token")
    return client


@pytest.mark.anyio
async def test_admin_serves_static_page_with_exact_compiled_permission() -> None:
    allowed = _admin(frozenset({"ops.pages.report.view"}))
    allowed.register_page(PageDefinition(page_id="report", path="/reports", label="Report"))
    async with _client(allowed) as client:
        response = await client.get("/reports")

    denied = _admin(frozenset({"ops.access"}))
    denied.register_page(PageDefinition(page_id="report", path="/reports", label="Report"))
    async with _client(denied) as client:
        forbidden = await client.get("/reports")

    assert response.status_code == 200
    assert "Report" in response.text
    assert forbidden.status_code == 403


@pytest.mark.anyio
async def test_admin_page_handler_runs_inside_operation_scope_with_principal() -> None:
    seen: list[tuple[str, str, bool]] = []

    async def handler(context: PageContext) -> PageResult[dict[str, bool]]:
        operation = current_operation_context()
        assert operation is not None
        assert operation.services is not None
        assert context.principal is not None
        seen.append(
            (
                operation.operation,
                context.principal.subject_id or "",
                operation.principal is context.principal,
            )
        )
        return PageResult(payload={"scoped": True}, message="Scoped")

    admin = _admin(frozenset({"ops.pages.report.view"}))
    admin.register_page(
        PageDefinition(
            page_id="report",
            path="/reports",
            label="Report",
            handler=DomainPageHandler(handler),
        )
    )
    app = admin.asgi()
    client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://localhost")
    client.cookies.set(SESSION_COOKIE_NAME, "token")

    async with LifespanDriver(app), client:
        response = await client.get("/reports")

    assert response.status_code == 200
    assert "Scoped" in response.text
    assert seen == [("page:report", "operator", True)]


def test_compiled_page_requires_authentication_at_runtime() -> None:
    admin = Admin(title="Operations", debug=True)
    admin.register_page(PageDefinition(page_id="report", path="/reports", label="Report"))

    with pytest.raises(RakitError) as caught:
        admin.asgi()

    assert caught.value.code == ErrorCode.CONFIG_INVALID
    assert "authentication" in caught.value.message


def test_mutating_page_requires_operation_idempotency_store() -> None:
    admin = _admin(frozenset({"ops.pages.rebuild.view"}), store=None)
    admin.register_page(
        PageDefinition(
            page_id="rebuild",
            path="/rebuild",
            label="Rebuild",
            handler=DomainPageHandler(lambda _context: PageRedirect("/reports")),
            mutating=True,
            transaction_policy=TransactionPolicy.DISABLED,
        )
    )

    with pytest.raises(RakitError) as caught:
        admin.asgi()

    assert caught.value.code == ErrorCode.CONFIG_INVALID
    assert "idempotency" in caught.value.message


def test_auto_page_requires_uow_managed_handler_before_runtime() -> None:
    admin = _admin(frozenset({"ops.pages.rebuild.view"}), store=_Store())
    admin.register_page(
        PageDefinition(
            page_id="rebuild",
            path="/rebuild",
            label="Rebuild",
            handler=DomainPageHandler(lambda _context: PageRedirect("/reports")),
            mutating=True,
            transaction_policy=TransactionPolicy.AUTO,
        )
    )

    with pytest.raises(RakitError) as caught:
        admin.asgi()

    assert caught.value.details["reason"] == "handler_not_uow_managed"


def test_auto_page_requires_registered_uow_provider() -> None:
    admin = _admin(frozenset({"ops.pages.rebuild.view"}), store=_Store())
    admin.register_page(
        PageDefinition(
            page_id="rebuild",
            path="/rebuild",
            label="Rebuild",
            handler=PreparedPageMutationHandler(
                lambda _context: object(),
                lambda _prepared, _context: PageRedirect("/reports"),
            ),
            mutating=True,
            transaction_policy=TransactionPolicy.AUTO,
        )
    )

    with pytest.raises(RakitError) as caught:
        admin.asgi()

    assert caught.value.details["reason"] == "operation_uow_not_configured"


@pytest.mark.anyio
async def test_page_and_existing_page_action_coexist_in_real_admin() -> None:
    permissions = frozenset(
        {
            "ops.pages.report.view",
            "ops.actions.refresh_report.execute",
        }
    )
    admin = _admin(permissions, store=_Store())
    action = ActionDefinition(
        action_id="refresh_report",
        label="Refresh",
        scope=ActionScope.PAGE,
        page_id="report",
        executor=DomainActionExecutor(lambda _context: ActionSuccess()),
    )
    admin.register_page(
        PageDefinition(page_id="report", path="/reports", label="Report"),
        actions=(action,),
    )

    async with _client(admin) as client:
        page = await client.get("/reports")
        action_form = await client.get("/reports/_actions/refresh_report")

    assert page.status_code == 200
    assert action_form.status_code == 200
    assert "Refresh" in action_form.text
