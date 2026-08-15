"""Task 5 synchronous bulk action web lifecycle regressions."""

import hashlib
import re
from dataclasses import dataclass
from typing import cast
from urllib.parse import urlencode

import httpx
import pytest
from rakit_core.actions import (
    ActionContext,
    ActionDefinition,
    ActionRejected,
    ActionScope,
    ActionSuccess,
    DomainActionExecutor,
    action_permission_requirement,
)
from rakit_core.bulk import BulkExecutionPolicy, BulkPolicy
from rakit_core.concurrency import ConcurrencyTokenService
from rakit_core.config import SecretValue
from rakit_core.crypto import TokenService
from rakit_core.definitions import CompiledActionDefinition, RouteDefinition
from rakit_core.idempotency import (
    IdempotencyReservation,
    IdempotencyStatus,
    OperationReceipt,
)
from rakit_core.identity import IdentityCodec, RecordIdentity
from rakit_core.mutations import OperationAuthorization
from rakit_web.bulk_runtime import (
    BulkActionBinding,
    _completed_response,
    build_bulk_action_routes,
)
from rakit_web.resource_routes import build_templates
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.types import Scope


class _MemoryIdempotencyStore:
    def __init__(self) -> None:
        self.claims: dict[str, tuple[str, OperationReceipt | None]] = {}
        self.statuses: dict[str, IdempotencyStatus] = {}
        self._tokens: dict[int, str] = {}
        self._next = 1

    async def begin(self, token_hash: str, *, fingerprint: str) -> IdempotencyReservation:
        existing = self.claims.get(token_hash)
        if existing is not None:
            existing_fingerprint, receipt = existing
            if existing_fingerprint != fingerprint:
                raise ValueError("fingerprint mismatch")
            return IdempotencyReservation(
                reservation_id=self._reservation_id(token_hash),
                status=self.statuses[token_hash],
                completed_receipt=receipt,
                claimed=False,
            )
        reservation = IdempotencyReservation(self._next, IdempotencyStatus.IN_PROGRESS)
        self._next += 1
        self._tokens[reservation.reservation_id] = token_hash
        self.claims[token_hash] = (fingerprint, None)
        self.statuses[token_hash] = IdempotencyStatus.IN_PROGRESS
        return reservation

    async def complete(
        self,
        reservation: IdempotencyReservation,
        receipt: OperationReceipt,
    ) -> None:
        token_hash = self._tokens[reservation.reservation_id]
        fingerprint, _ = self.claims[token_hash]
        self.claims[token_hash] = (fingerprint, receipt)
        self.statuses[token_hash] = IdempotencyStatus.COMPLETED

    async def release(self, reservation: IdempotencyReservation) -> None:
        token_hash = self._tokens.get(reservation.reservation_id)
        if token_hash is not None:
            self.claims.pop(token_hash, None)
            self.statuses.pop(token_hash, None)

    async def fail_final(self, reservation: IdempotencyReservation) -> None:
        token_hash = self._tokens[reservation.reservation_id]
        self.statuses[token_hash] = IdempotencyStatus.FAILED_FINAL

    def receipt(self, submission_token: str) -> OperationReceipt | None:
        token_hash = hashlib.sha256(submission_token.encode()).hexdigest()
        return self.claims[token_hash][1]

    def _reservation_id(self, token_hash: str) -> int:
        return next(
            reservation_id
            for reservation_id, candidate in self._tokens.items()
            if candidate == token_hash
        )


@dataclass
class _Record:
    id: int
    version: int = 1


class _Harness:
    def __init__(
        self,
        *,
        execution: BulkExecutionPolicy = BulkExecutionPolicy.ATOMIC,
        require_concurrency_snapshot: bool = False,
        reject_id: int | None = None,
    ) -> None:
        self.codec = IdentityCodec()
        self.records = {1: _Record(1), 2: _Record(2), 3: _Record(3)}
        self.calls: list[int] = []
        self.reject_id = reject_id
        self.token_service = TokenService.single_key(
            key_id="bulk",
            value=SecretValue("x" * 32),
            admin_id="ops",
        )
        self.idempotency = _MemoryIdempotencyStore()
        permission = action_permission_requirement("archive", admin_id="ops")

        def execute(context: ActionContext):
            assert context.identity is not None
            record_id = cast(int, context.identity.values["id"])
            self.calls.append(record_id)
            if record_id == self.reject_id:
                return ActionRejected(
                    errors={"status": "locked"},
                    message="Order is locked",
                )
            return ActionSuccess(message="Archived")

        self.action = ActionDefinition(
            action_id="archive",
            label="Archive selected",
            scope=ActionScope.BULK,
            resource_id="orders",
            permission=permission,
            executor=DomainActionExecutor(execute),
            bulk_policy=BulkPolicy(
                execution=execution,
                require_concurrency_snapshot=require_concurrency_snapshot,
            ),
        )
        self.compiled = CompiledActionDefinition(
            definition=self.action,
            permission=permission,
        )
        self.route = RouteDefinition(
            route_name="resource:orders:action:archive",
            methods=("GET", "POST"),
            path="/orders/_actions/archive",
            owner_id="orders",
        )

    async def authorize(
        self,
        _request: Request,
        compiled: CompiledActionDefinition,
        identity: RecordIdentity | None,
    ) -> OperationAuthorization:
        return OperationAuthorization.for_requirement(
            admin_id="ops",
            resource_id="orders",
            operation="action:archive",
            principal_id="operator",
            requirement=compiled.permission,
            target_identity=identity,
        )

    async def load_record(self, identity: RecordIdentity) -> object | None:
        return self.records.get(cast(int, identity.values["id"]))

    def encoded(self, *record_ids: int) -> list[str]:
        return [
            self.codec.encode(RecordIdentity(values={"id": record_id}))
            for record_id in record_ids
        ]

    def app(self) -> Starlette:
        async def allow(_request: Request) -> bool:
            return True

        needs_snapshot = bool(
            self.action.bulk_policy is not None
            and self.action.bulk_policy.require_concurrency_snapshot
        )
        record_version = (
            (lambda record: cast(_Record, record).version) if needs_snapshot else None
        )
        binding = BulkActionBinding(
            routes=((self.route, self.compiled),),
            templates=build_templates(()),
            codec=self.codec,
            verify_csrf=allow,
            verify_submission_token=allow,
            issue_submission_token=lambda _request: "issued-token",
            authorize_action=self.authorize,
            load_record=self.load_record,
            token_service=self.token_service,
            idempotency_store=self.idempotency,
            concurrency=(
                ConcurrencyTokenService(self.token_service) if needs_snapshot else None
            ),
            concurrency_resource_id="orders" if needs_snapshot else None,
            record_version=record_version,
        )
        return Starlette(routes=build_bulk_action_routes(binding))


async def _post(
    client: httpx.AsyncClient,
    selected: list[str],
    *,
    submission_token: str,
    concurrency_tokens: list[str] | None = None,
    confirmation_token: str | None = None,
) -> httpx.Response:
    data: list[tuple[str, str]] = [
        ("csrf_token", "csrf"),
        ("submission_token", submission_token),
        *(("selected", identity) for identity in selected),
        *(("concurrency_token", token) for token in (concurrency_tokens or [])),
    ]
    if confirmation_token is not None:
        data.append(("confirmation_token", confirmation_token))
    return await client.post(
        "/orders/_actions/archive",
        content=urlencode(data),
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        follow_redirects=False,
    )


@pytest.mark.anyio
async def test_atomic_bulk_success_completes_and_replays_without_reexecution() -> None:
    harness = _Harness()
    selected = harness.encoded(1, 2)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=harness.app()),
        base_url="http://test",
    ) as client:
        first = await _post(client, selected, submission_token="same-token")
        replay = await _post(client, selected, submission_token="same-token")

    assert first.status_code == 303
    assert first.headers["location"] == "/orders"
    assert replay.status_code == 303
    assert replay.headers["location"] == "/orders"
    assert harness.calls == [1, 2]
    receipt = harness.idempotency.receipt("same-token")
    assert receipt is not None
    assert receipt.result_kind == "bulk"
    assert receipt.payload == {
        "selected": 2,
        "succeeded": 2,
        "rejected": 0,
        "skipped": 0,
    }


@pytest.mark.anyio
async def test_bulk_selection_deduplicates_identities_before_execution() -> None:
    harness = _Harness()
    first, second = harness.encoded(1, 2)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=harness.app()),
        base_url="http://test",
    ) as client:
        response = await _post(
            client,
            [first, first, second, second],
            submission_token="dedupe-token",
        )

    assert response.status_code == 303
    assert harness.calls == [1, 2]


@pytest.mark.anyio
async def test_atomic_rejection_releases_claim_and_allows_safe_retry() -> None:
    harness = _Harness(reject_id=2)
    selected = harness.encoded(1, 2, 3)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=harness.app()),
        base_url="http://test",
    ) as client:
        first = await _post(client, selected, submission_token="retryable-token")
        second = await _post(client, selected, submission_token="retryable-token")

    assert first.status_code == 409
    assert second.status_code == 409
    assert harness.calls == [1, 2, 1, 2]
    token_hash = hashlib.sha256(b"retryable-token").hexdigest()
    assert token_hash not in harness.idempotency.claims


@pytest.mark.anyio
async def test_best_effort_partial_success_completes_safe_receipt() -> None:
    harness = _Harness(
        execution=BulkExecutionPolicy.BEST_EFFORT,
        reject_id=2,
    )
    selected = harness.encoded(1, 2, 3)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=harness.app()),
        base_url="http://test",
    ) as client:
        response = await _post(client, selected, submission_token="partial-token")

    assert response.status_code == 303
    assert harness.calls == [1, 2, 3]
    receipt = harness.idempotency.receipt("partial-token")
    assert receipt is not None
    assert receipt.payload == {
        "selected": 3,
        "succeeded": 2,
        "rejected": 1,
        "skipped": 0,
    }


@pytest.mark.anyio
async def test_stale_bulk_concurrency_snapshot_rejects_before_executor() -> None:
    harness = _Harness(require_concurrency_snapshot=True)
    selected = harness.encoded(1, 2)
    query = urlencode([("selected", identity) for identity in selected])
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=harness.app()),
        base_url="http://test",
    ) as client:
        get_response = await client.get(f"/orders/_actions/archive?{query}")
        assert get_response.status_code == 200
        concurrency_tokens = re.findall(
            r'name="concurrency_token" value="([^"]+)"',
            get_response.text,
        )
        assert len(concurrency_tokens) == 2
        harness.records[2].version += 1
        post_response = await _post(
            client,
            selected,
            submission_token="stale-token",
            concurrency_tokens=concurrency_tokens,
        )

    assert post_response.status_code == 409
    assert "changed" in post_response.text
    assert harness.calls == []


@pytest.mark.anyio
async def test_missing_selected_record_fails_closed_before_executor() -> None:
    harness = _Harness()
    selected = harness.encoded(1, 99)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=harness.app()),
        base_url="http://test",
    ) as client:
        response = await _post(client, selected, submission_token="missing-token")

    assert response.status_code == 404
    assert harness.calls == []


def _request(*, htmx: bool = False) -> Request:
    headers = [(b"hx-request", b"true")] if htmx else []
    scope = cast(
        Scope,
        {
            "type": "http",
            "http_version": "1.1",
            "method": "POST",
            "scheme": "http",
            "path": "/orders/_actions/archive",
            "raw_path": b"/orders/_actions/archive",
            "query_string": b"",
            "headers": headers,
            "client": ("test", 1234),
            "server": ("test", 80),
            "root_path": "",
        },
    )
    return Request(scope)


def test_completed_bulk_receipt_rejects_external_redirect() -> None:
    response = _completed_response(
        _request(),
        OperationReceipt(
            operation_id="1",
            status="succeeded",
            result_kind="bulk",
            redirect_route="https://attacker.example/steal",
            payload={"selected": 2, "succeeded": 2},
        ),
        "/orders",
    )

    assert response.status_code == 409
    assert "cannot be replayed" in bytes(response.body).decode()
