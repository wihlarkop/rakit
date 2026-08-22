from __future__ import annotations

from contextlib import AbstractAsyncContextManager
from datetime import UTC, datetime, timedelta

import pytest
from rakit import Admin, SecretValue
from rakit_core.actions import ActionDefinition, ActionScope, ActionSuccess, DomainActionExecutor
from rakit_core.auth import Principal, SessionRecord
from rakit_core.definitions import PageDefinition
from rakit_core.errors import ErrorCode, RakitError
from rakit_core.events import EventPublisher
from rakit_core.idempotency import IdempotencyReservation, OperationReceipt
from rakit_core.operations import OperationContext, OperationExecutorCapabilities
from rakit_core.transactions import OperationUnitOfWork, TransactionPolicy


class _AuthBackend:
    async def authenticate(self, identifier: str, password: str) -> Principal | None:
        del identifier, password
        return None

    async def resolve_principal(self, subject_id: str) -> Principal | None:
        del subject_id
        return None


class _SessionStore:
    production_safe = True

    async def create(self, principal: Principal) -> tuple[str, SessionRecord]:
        del principal
        now = datetime.now(UTC)
        return "token", SessionRecord(
            session_id="session",
            subject_id="operator",
            created_at=now,
            last_seen_at=now,
            idle_expires_at=now + timedelta(hours=1),
            absolute_expires_at=now + timedelta(days=1),
        )

    async def resolve(self, raw_token: str) -> SessionRecord | None:
        del raw_token
        return None

    async def rotate(self, session_id: str) -> tuple[str, SessionRecord]:
        del session_id
        raise NotImplementedError

    async def revoke(self, session_id: str) -> None:
        del session_id


class _IdempotencyStore:
    production_safe = True

    async def begin(self, token_hash: str, *, fingerprint: str) -> IdempotencyReservation:
        del token_hash, fingerprint
        raise AssertionError("setup validation must fail before idempotency begins")

    async def complete(
        self, reservation: IdempotencyReservation, receipt: OperationReceipt
    ) -> None:
        del reservation, receipt

    async def release(self, reservation: IdempotencyReservation) -> None:
        del reservation

    async def fail_final(self, reservation: IdempotencyReservation) -> None:
        del reservation


class _ManagedExecutor(DomainActionExecutor):
    capabilities = OperationExecutorCapabilities(participates_in_uow=True)


class _NeverOpenedFactory:
    def open(
        self,
        *,
        policy: TransactionPolicy,
        event_publisher: EventPublisher | None,
        operation_context: OperationContext,
    ) -> AbstractAsyncContextManager[OperationUnitOfWork]:
        del policy, event_publisher, operation_context
        raise AssertionError("setup validation must fail before opening a UoW")


def test_mutating_page_action_rejects_ambiguous_uow_providers() -> None:
    admin = Admin(
        admin_id="ops",
        title="Ops",
        debug=True,
        secret_key=SecretValue("x" * 32),
        auth_backend=_AuthBackend(),
        session_store=_SessionStore(),
        operation_idempotency_store=_IdempotencyStore(),
    )
    admin.builder.register_unit_of_work_factory("persistence.first", _NeverOpenedFactory())
    admin.builder.register_unit_of_work_factory("persistence.second", _NeverOpenedFactory())
    admin.builder.add_page(PageDefinition(page_id="report", path="/reports", label="Report"))
    admin.builder.add_action(
        ActionDefinition(
            action_id="rebuild",
            label="Rebuild",
            scope=ActionScope.PAGE,
            page_id="report",
            mutating=True,
            transaction_policy=TransactionPolicy.AUTO,
            executor=_ManagedExecutor(lambda _context: ActionSuccess()),
        )
    )

    with pytest.raises(RakitError) as caught:
        admin.asgi()

    assert caught.value.code == ErrorCode.CONFIG_INVALID
    assert caught.value.details["reason"] == "operation_uow_ambiguous"
    assert caught.value.details["action_id"] == "rebuild"
    assert caught.value.details["owner"] == "report"
