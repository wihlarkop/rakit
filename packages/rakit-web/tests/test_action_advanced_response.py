"""Focused regression coverage for explicit advanced action web responses."""

from collections.abc import Awaitable, Callable
from typing import Any, cast

import httpx
import pytest
from rakit_core.actions import (
    ActionAdvancedResponse,
    ActionContext,
    ActionDefinition,
    ActionResponseKind,
    ActionScope,
    DomainActionExecutor,
    action_permission_requirement,
)
from rakit_core.definitions import CompiledActionDefinition, RouteDefinition
from rakit_core.errors import ErrorCode, RakitError
from rakit_core.idempotency import (
    IdempotencyReservation,
    IdempotencyStatus,
    OperationReceipt,
)
from rakit_core.identity import IdentityCodec, RecordIdentity
from rakit_core.mutations import OperationAuthorization
from rakit_core.permissions import PermissionRequirement
from rakit_web.action_routes import (
    ActionBinding,
    AdvancedActionResponseAdapter,
    build_action_routes,
)
from rakit_web.resource_routes import build_templates
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import Response


class _MemoryIdempotencyStore:
    def __init__(self) -> None:
        self._next = 1
        self._claims: dict[str, tuple[str, IdempotencyStatus, OperationReceipt | None]] = {}
        self._tokens: dict[int, str] = {}

    async def begin(self, token_hash: str, *, fingerprint: str) -> IdempotencyReservation:
        existing = self._claims.get(token_hash)
        if existing is not None:
            existing_fingerprint, status, receipt = existing
            if existing_fingerprint != fingerprint:
                raise ValueError("fingerprint mismatch")
            return IdempotencyReservation(
                reservation_id=self._tokens_by_hash(token_hash),
                status=status,
                completed_receipt=receipt,
                claimed=False,
            )
        reservation_id = self._next
        self._next += 1
        self._tokens[reservation_id] = token_hash
        self._claims[token_hash] = (fingerprint, IdempotencyStatus.IN_PROGRESS, None)
        return IdempotencyReservation(reservation_id, IdempotencyStatus.IN_PROGRESS)

    async def complete(
        self, reservation: IdempotencyReservation, receipt: OperationReceipt
    ) -> None:
        token_hash = self._tokens[reservation.reservation_id]
        fingerprint, _, _ = self._claims[token_hash]
        self._claims[token_hash] = (fingerprint, IdempotencyStatus.COMPLETED, receipt)

    async def release(self, reservation: IdempotencyReservation) -> None:
        token_hash = self._tokens.get(reservation.reservation_id)
        if token_hash is not None:
            self._claims.pop(token_hash, None)

    async def fail_final(self, reservation: IdempotencyReservation) -> None:
        token_hash = self._tokens[reservation.reservation_id]
        fingerprint, _, receipt = self._claims[token_hash]
        self._claims[token_hash] = (fingerprint, IdempotencyStatus.FAILED_FINAL, receipt)

    def status(self) -> IdempotencyStatus:
        assert len(self._claims) == 1
        return next(iter(self._claims.values()))[1]

    def receipt(self) -> OperationReceipt | None:
        assert len(self._claims) == 1
        return next(iter(self._claims.values()))[2]

    def _tokens_by_hash(self, token_hash: str) -> int:
        return next(
            reservation_id
            for reservation_id, candidate_hash in self._tokens.items()
            if candidate_hash == token_hash
        )


async def _allow(_request: object) -> bool:
    return True


def _advanced_app(
    *,
    adapter: AdvancedActionResponseAdapter | None,
) -> tuple[Starlette, _MemoryIdempotencyStore, list[str]]:
    calls: list[str] = []
    store = _MemoryIdempotencyStore()

    def execute(_context: ActionContext) -> ActionAdvancedResponse:
        calls.append("executed")
        return ActionAdvancedResponse(
            kind=ActionResponseKind.ADVANCED,
            payload={"secret": "do-not-persist"},
        )

    action = ActionDefinition(
        action_id="export",
        label="Export",
        scope=ActionScope.PAGE,
        page_id="tools",
        permission=action_permission_requirement("export", admin_id="ops"),
        executor=DomainActionExecutor(execute),
    )
    compiled = CompiledActionDefinition(
        definition=action,
        permission=cast(PermissionRequirement, action.permission),
    )

    async def authorize(
        _request: Request,
        compiled_action: CompiledActionDefinition,
        identity: RecordIdentity | None,
    ) -> OperationAuthorization | None:
        assert identity is None
        return OperationAuthorization.for_requirement(
            admin_id="ops",
            resource_id="tools",
            operation="action:export",
            principal_id="tester",
            requirement=compiled_action.permission,
            target_identity=None,
        )

    binding = ActionBinding(
        routes=(
            (
                RouteDefinition(
                    route_name="page:tools:action:export",
                    methods=("GET", "POST"),
                    path="/tools/_actions/export",
                    owner_id="tools",
                ),
                compiled,
            ),
        ),
        templates=build_templates(()),
        codec=IdentityCodec(),
        verify_csrf=_allow,
        verify_submission_token=_allow,
        issue_submission_token=lambda _request: "issued-token",
        authorize_action=authorize,
        idempotency_store=store,
        advanced_response_adapter=adapter,
    )
    return Starlette(routes=build_action_routes(binding)), store, calls


async def _post(client: httpx.AsyncClient, token: str = "shared-token") -> httpx.Response:
    return await client.post(
        "/tools/_actions/export",
        data={"csrf_token": "csrf", "submission_token": token},
        follow_redirects=False,
    )


@pytest.mark.anyio
async def test_advanced_response_adapter_replays_as_terminal_without_payload() -> None:
    def adapter(_request: Request, result: ActionAdvancedResponse) -> Response:
        assert result.payload == {"secret": "do-not-persist"}
        return Response("export-ready", status_code=202, headers={"X-Action": result.kind.value})

    app, store, calls = _advanced_app(adapter=adapter)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        first = await _post(client)
        duplicate = await _post(client)

    assert first.status_code == 202
    assert first.text == "export-ready"
    assert first.headers["x-action"] == "advanced"
    assert duplicate.status_code == 409
    assert "cannot be replayed" in duplicate.text
    assert calls == ["executed"]
    assert store.status() is IdempotencyStatus.COMPLETED
    receipt = store.receipt()
    assert receipt is not None
    assert receipt.result_kind == "advanced"
    assert receipt.payload is None


@pytest.mark.anyio
async def test_async_advanced_response_adapter_is_supported() -> None:
    async def adapter(_request: Request, _result: ActionAdvancedResponse) -> Response:
        return Response("stream-ready", status_code=206)

    app, store, calls = _advanced_app(adapter=adapter)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await _post(client, "async-adapter-token")

    assert response.status_code == 206
    assert response.text == "stream-ready"
    assert calls == ["executed"]
    assert store.status() is IdempotencyStatus.COMPLETED


@pytest.mark.anyio
async def test_missing_advanced_adapter_terminalizes_reservation() -> None:
    app, store, calls = _advanced_app(adapter=None)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        with pytest.raises(RakitError) as exc_info:
            await _post(client, "missing-adapter-token")
        duplicate = await _post(client, "missing-adapter-token")

    assert exc_info.value.code is ErrorCode.CONFIG_INVALID
    assert "configured web response adapter" in exc_info.value.message
    assert duplicate.status_code == 409
    assert "cannot be retried" in duplicate.text
    assert calls == ["executed"]
    assert store.status() is IdempotencyStatus.FAILED_FINAL


@pytest.mark.anyio
async def test_invalid_advanced_adapter_result_terminalizes_reservation() -> None:
    def invalid_adapter(_request: Request, _result: ActionAdvancedResponse) -> Any:
        return "not-a-response"

    adapter = cast(AdvancedActionResponseAdapter, invalid_adapter)
    app, store, calls = _advanced_app(adapter=adapter)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        with pytest.raises(RakitError) as exc_info:
            await _post(client, "invalid-adapter-token")

    assert exc_info.value.code is ErrorCode.CONFIG_INVALID
    assert "must return a Starlette Response" in exc_info.value.message
    assert calls == ["executed"]
    assert store.status() is IdempotencyStatus.FAILED_FINAL
