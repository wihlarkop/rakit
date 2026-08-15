"""Plan 05 Task 4 Correction C2A: real Admin transaction-capability composition."""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta
from typing import cast

import httpx
import pytest
from conftest import LifespanDriver
from rakit import Admin, ResourceAdmin, SecretValue
from rakit_core.actions import (
    ActionDefinition,
    ActionScope,
    ActionSuccess,
    DomainActionExecutor,
    PreparedMutationExecutor,
)
from rakit_core.auth import Principal, SessionRecord
from rakit_core.concurrency import AttributeVersionProvider
from rakit_core.datasource import DataSourceCapabilities
from rakit_core.definitions import PageDefinition
from rakit_core.di import ServiceScope
from rakit_core.errors import ErrorCode, RakitError
from rakit_core.idempotency import IdempotencyReservation, IdempotencyStatus, OperationReceipt
from rakit_core.operations import OperationExecutorCapabilities
from rakit_core.transactions import OperationUnitOfWorkFactory, TransactionPolicy


class _AuthBackend:
    def __init__(self, permissions: frozenset[str]) -> None:
        self.permissions = permissions

    def _principal(self) -> Principal:
        return Principal(subject_id="1", authenticated=True, permissions=self.permissions)

    async def authenticate(self, identifier: str, password: str) -> Principal | None:
        return self._principal() if (identifier, password) == ("admin@example.com", "password") else None

    async def resolve_principal(self, subject_id: str) -> Principal | None:
        return self._principal() if subject_id == "1" else None


class _SessionStore:
    production_safe = True

    def __init__(self) -> None:
        self.records: dict[str, SessionRecord] = {}
        self.tokens: dict[str, str] = {}

    async def create(self, principal: Principal) -> tuple[str, SessionRecord]:
        now = datetime.now(UTC)
        record = SessionRecord(
            session_id="1",
            subject_id="1",
            created_at=now,
            last_seen_at=now,
            idle_expires_at=now + timedelta(hours=1),
            absolute_expires_at=now + timedelta(days=1),
        )
        self.records["1"] = record
        self.tokens["session-token"] = "1"
        return "session-token", record

    async def resolve(self, raw_token: str) -> SessionRecord | None:
        session_id = self.tokens.get(raw_token)
        return self.records.get(session_id) if session_id is not None else None

    async def rotate(self, session_id: str) -> tuple[str, SessionRecord]:
        raise NotImplementedError

    async def revoke(self, session_id: str) -> None:
        self.records.pop(session_id, None)


class _IdempotencyStore:
    production_safe = True

    async def begin(self, token_hash: str, *, fingerprint: str) -> IdempotencyReservation:
        return IdempotencyReservation(1, IdempotencyStatus.IN_PROGRESS)

    async def complete(self, reservation: IdempotencyReservation, receipt: OperationReceipt) -> None:
        return None

    async def release(self, reservation: IdempotencyReservation) -> None:
        return None

    async def fail_final(self, reservation: IdempotencyReservation) -> None:
        return None


class _Record:
    id = 1
    version = 1


class _Source:
    capabilities = DataSourceCapabilities(read=True)
    fields = ("id", "version")
    identity_fields = ("id",)

    async def list(self, query):
        raise AssertionError

    async def count(self, query):
        raise AssertionError

    async def detail(self, identity):
        return _Record()


class _RecordAdmin(ResourceAdmin):
    resource_id = "records"
    path = "/records"
    label = "Records"
    singular_label = "Record"
    list_fields = ("id",)
    detail_fields = ("id", "version")
    data_source = _Source()


class _ManagedExecutor(DomainActionExecutor):
    capabilities = OperationExecutorCapabilities(participates_in_uow=True)


class _NeverOpenedFactory:
    def open(self, **kwargs):
        raise AssertionError("C2A setup validation must fail before opening the UoW")


def _admin(*, permissions: frozenset[str]) -> Admin:
    return Admin(
        admin_id="ops",
        title="Ops",
        debug=True,
        secret_key=SecretValue("x" * 32),
        auth_backend=_AuthBackend(permissions),
        session_store=_SessionStore(),
        operation_idempotency_store=_IdempotencyStore(),
    )


async def _login(client: httpx.AsyncClient) -> str:
    page = await client.get("/auth/login")
    login_csrf = page.cookies["rakit_login_csrf"]
    client.cookies.set("rakit_login_csrf", login_csrf)
    response = await client.post(
        "/auth/login",
        data={
            "identifier": "admin@example.com",
            "password": "password",
            "login_csrf_token": login_csrf,
        },
        follow_redirects=False,
    )
    assert response.status_code == 303
    client.cookies.set("rakit_session", response.cookies["rakit_session"])
    csrf = response.cookies["rakit_csrf"]
    client.cookies.set("rakit_csrf", csrf, domain="localhost.local", path="/")
    return csrf


def _tokens(html: str) -> dict[str, str]:
    return dict(re.findall(r'name="([^"]+)" value="([^"]*)"', html))


@pytest.mark.anyio
async def test_read_only_domain_action_runs_without_persistence_uow() -> None:
    calls: list[str] = []
    action = ActionDefinition(
        action_id="refresh",
        label="Refresh",
        scope=ActionScope.PAGE,
        page_id="report",
        executor=DomainActionExecutor(lambda _context: calls.append("ran") or ActionSuccess()),
    )
    admin = _admin(permissions=frozenset({"ops.actions.refresh.execute"}))
    admin.builder.add_page(PageDefinition(page_id="report", path="/reports", label="Report"))
    admin.builder.add_action(action)
    app = admin.asgi()
    async with (
        LifespanDriver(app),
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://localhost"
        ) as client,
    ):
        csrf = await _login(client)
        page = await client.get("/reports/_actions/refresh")
        token = _tokens(page.text)["submission_token"]
        response = await client.post(
            "/reports/_actions/refresh",
            data={"csrf_token": csrf, "submission_token": token},
            follow_redirects=False,
        )
    assert response.status_code == 303
    assert calls == ["ran"]


@pytest.mark.anyio
async def test_disabled_domain_side_effect_runs_without_uow_guarantee() -> None:
    calls: list[str] = []
    action = ActionDefinition(
        action_id="deploy",
        label="Deploy",
        scope=ActionScope.PAGE,
        page_id="report",
        mutating=True,
        transaction_policy=TransactionPolicy.DISABLED,
        executor=DomainActionExecutor(lambda _context: calls.append("ran") or ActionSuccess()),
    )
    admin = _admin(permissions=frozenset({"ops.actions.deploy.execute"}))
    admin.builder.add_page(PageDefinition(page_id="report", path="/reports", label="Report"))
    admin.builder.add_action(action)
    app = admin.asgi()
    async with (
        LifespanDriver(app),
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://localhost"
        ) as client,
    ):
        csrf = await _login(client)
        page = await client.get("/reports/_actions/deploy")
        token = _tokens(page.text)["submission_token"]
        response = await client.post(
            "/reports/_actions/deploy",
            data={"csrf_token": csrf, "submission_token": token},
            follow_redirects=False,
        )
    assert response.status_code == 303
    assert calls == ["ran"]


def test_mutating_auto_domain_action_fails_admin_setup() -> None:
    action = ActionDefinition(
        action_id="write",
        label="Write",
        scope=ActionScope.PAGE,
        page_id="report",
        mutating=True,
        transaction_policy=TransactionPolicy.AUTO,
        executor=DomainActionExecutor(lambda _context: ActionSuccess()),
    )
    admin = _admin(permissions=frozenset({"ops.actions.write.execute"}))
    admin.builder.add_page(PageDefinition(page_id="report", path="/reports", label="Report"))
    admin.builder.add_action(action)
    with pytest.raises(RakitError) as caught:
        admin.asgi()
    assert caught.value.code == ErrorCode.CONFIG_INVALID
    assert caught.value.details["reason"] == "executor_not_uow_managed"


def test_managed_auto_action_requires_registered_uow_factory() -> None:
    action = ActionDefinition(
        action_id="write",
        label="Write",
        scope=ActionScope.PAGE,
        page_id="report",
        mutating=True,
        transaction_policy=TransactionPolicy.AUTO,
        executor=_ManagedExecutor(lambda _context: ActionSuccess()),
    )
    admin = _admin(permissions=frozenset({"ops.actions.write.execute"}))
    admin.builder.add_page(PageDefinition(page_id="report", path="/reports", label="Report"))
    admin.builder.add_action(action)
    with pytest.raises(RakitError) as caught:
        admin.asgi()
    assert caught.value.details["reason"] == "operation_uow_not_configured"


def test_prepared_concurrent_action_fails_until_c2b_atomic_path_exists() -> None:
    action = ActionDefinition(
        action_id="approve",
        label="Approve",
        scope=ActionScope.RECORD,
        resource_id="records",
        mutating=True,
        transaction_policy=TransactionPolicy.AUTO,
        requires_concurrency=True,
        executor=PreparedMutationExecutor(
            lambda _context: {}, lambda _plan, _context: ActionSuccess()
        ),
    )
    admin = _admin(permissions=frozenset({"ops.actions.approve.execute"}))
    admin.register(_RecordAdmin)
    admin.register_concurrency_provider("records", AttributeVersionProvider("version"))
    admin.builder.registry.add_value(
        OperationUnitOfWorkFactory,
        cast(OperationUnitOfWorkFactory, _NeverOpenedFactory()),
        scope=ServiceScope.APPLICATION,
    )
    admin.builder.add_action(action)
    with pytest.raises(RakitError) as caught:
        admin.asgi()
    assert caught.value.code == ErrorCode.CONFIG_INVALID
    assert caught.value.details["reason"] == "atomic_concurrency_not_supported"
