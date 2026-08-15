"""PLAN 05 TASK 4 CORRECTION B2B2: generic RECORD concurrency for actions.

``ActionDefinition.requires_concurrency`` is a Task-4 RECORD-only flag; the
runtime capability is a backend-neutral ``ConcurrencyVersionProvider``
registered per resource (Task 5 owns bulk concurrency snapshots).
"""

from datetime import timedelta

import pytest
from rakit_core.actions import ActionDefinition, ActionScope, ActionSuccess, DomainActionExecutor
from rakit_core.concurrency import (
    AttributeVersionProvider,
    ConcurrencyTokenService,
    SnapshotVersionProvider,
)
from rakit_core.config import SecretValue
from rakit_core.crypto import TokenService
from rakit_core.errors import RakitError
from rakit_core.identity import RecordIdentity


def _executor() -> DomainActionExecutor:
    return DomainActionExecutor(lambda _context: ActionSuccess())


def test_requires_concurrency_is_valid_only_for_record_scope() -> None:
    for scope in (ActionScope.PAGE, ActionScope.RESOURCE, ActionScope.BULK):
        with pytest.raises(ValueError, match="RECORD scope"):
            ActionDefinition(
                action_id="x",
                label="X",
                scope=scope,
                resource_id="orders" if scope is not ActionScope.PAGE else None,
                page_id="report" if scope is ActionScope.PAGE else None,
                requires_concurrency=True,
                executor=_executor(),
            )

    record = ActionDefinition(
        action_id="approve",
        label="Approve",
        scope=ActionScope.RECORD,
        resource_id="orders",
        requires_concurrency=True,
        executor=_executor(),
    )
    assert record.requires_concurrency is True


def test_concurrency_token_is_bound_to_resource_and_identity() -> None:
    token_service = TokenService.single_key(
        key_id="test", value=SecretValue("x" * 32), admin_id="ops"
    )
    concurrency = ConcurrencyTokenService(token_service)
    provider = AttributeVersionProvider("version")

    class Record:
        version = 3

    identity_a = RecordIdentity(values={"id": 1})
    identity_b = RecordIdentity(values={"id": 2})
    token = concurrency.issue("orders", identity_a, provider.version_for(Record()))

    assert concurrency.verify(token, "orders", identity_a, 3) is not None
    with pytest.raises(RakitError):
        concurrency.verify(token, "orders", identity_b, 3)
    with pytest.raises(RakitError):
        concurrency.verify(token, "other_resource", identity_a, 3)
    with pytest.raises(RakitError):
        concurrency.verify(token, "orders", identity_a, 4)


def test_snapshot_provider_is_usable_with_token_service() -> None:
    token_service = TokenService.single_key(
        key_id="test", value=SecretValue("x" * 32), admin_id="ops"
    )
    concurrency = ConcurrencyTokenService(token_service, ttl=timedelta(minutes=15))
    provider = SnapshotVersionProvider(fields=("revision",))

    class Record:
        revision = 7

    identity = RecordIdentity(values={"id": 1})
    token = concurrency.issue("orders", identity, provider.version_for(Record()))

    assert concurrency.verify(token, "orders", identity, provider.version_for(Record())) is not None

    class Changed:
        revision = 8

    with pytest.raises(RakitError):
        concurrency.verify(token, "orders", identity, provider.version_for(Changed()))
