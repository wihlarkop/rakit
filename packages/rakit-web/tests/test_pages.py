"""Custom page web runtime regression coverage."""

from collections.abc import Awaitable, Callable

import httpx
import pytest
from pydantic import BaseModel, Field
from rakit_core.compiler import ApplicationBuilder, compile_application
from rakit_core.definitions import CompiledPageDefinition, PageDefinition, RouteDefinition
from rakit_core.errors import RakitError
from rakit_core.idempotency import (
    IdempotencyReservation,
    IdempotencyStatus,
    OperationReceipt,
)
from rakit_core.mutations import OperationAuthorization
from rakit_core.pages import DomainPageHandler, PageContext, PageRedirect, PageRejected, PageResult
from rakit_core.permissions import PermissionRequirement
from rakit_core.transactions import TransactionPolicy
from rakit_web.page_routes import PageBinding, build_page_routes
from rakit_web.resource_routes import build_templates
from starlette.applications import Starlette
from starlette.requests import Request


class _ReadInput(BaseModel):
    limit: int = Field(ge=1, le=10)


class _WriteInput(BaseModel):
    reason: str = Field(min_length=2)


class _MemoryIdempotencyStore:
    production_safe = True

    def __init__(self) -> None:
        self._next_id = 1
        self._claims: dict[str, tuple[str, IdempotencyStatus, OperationReceipt | None]] = {}
        self._keys: dict[int, str] = {}
        self.begin_calls = 0
        self.release_calls = 0
        self.fail_final_calls = 0

    async def begin(self, token_hash: str, *, fingerprint: str) -> IdempotencyReservation:
        self.begin_calls += 1
        existing = self._claims.get(token_hash)
        if existing is not None:
            old_fingerprint, status, receipt = existing
            if old_fingerprint != fingerprint:
                raise ValueError("fingerprint mismatch")
            return IdempotencyReservation(
                reservation_id=1,
                status=status,
                completed_receipt=receipt,
                claimed=status in (IdempotencyStatus.FAILED_RETRYABLE, IdempotencyStatus.EXPIRED),
            )
        reservation_id = self._next_id
        self._next_id += 1
        self._keys[reservation_id] = token_hash
        self._claims[token_hash] = (fingerprint, IdempotencyStatus.IN_PROGRESS, None)
        return IdempotencyReservation(reservation_id, IdempotencyStatus.IN_PROGRESS)

    async def complete(
        self, reservation: IdempotencyReservation, receipt: OperationReceipt
    ) -> None:
        key = self._keys[reservation.reservation_id]
        fingerprint, _, _ = self._claims[key]
        self._claims[key] = (fingerprint, IdempotencyStatus.COMPLETED, receipt)

    async def release(self, reservation: IdempotencyReservation) -> None:
        self.release_calls += 1
        key = self._keys[reservation.reservation_id]
        fingerprint, _, _ = self._claims[key]
        self._claims[key] = (fingerprint, IdempotencyStatus.FAILED_RETRYABLE, None)

    async def fail_final(self, reservation: IdempotencyReservation) -> None:
        self.fail_final_calls += 1
        key = self._keys[reservation.reservation_id]
        fingerprint, _, _ = self._claims[key]
        self._claims[key] = (fingerprint, IdempotencyStatus.FAILED_FINAL, None)


def _compiled_page(
    definition: PageDefinition,
) -> tuple[RouteDefinition, CompiledPageDefinition]:
    builder = ApplicationBuilder(admin_id="ops")
    builder.add_page(definition)
    compiled = compile_application(builder)
    route = next(
        route for route in compiled.routes if route.route_name == f"page:{definition.page_id}"
    )
    return route, compiled.compiled_pages[0]


def _authorization(permission: PermissionRequirement, page_id: str) -> OperationAuthorization:
    return OperationAuthorization.for_requirement(
        admin_id="ops",
        resource_id=page_id,
        operation=f"page:{page_id}",
        principal_id="operator",
        requirement=permission,
    )


def _app(
    definition: PageDefinition,
    *,
    store: _MemoryIdempotencyStore | None = None,
    verify_csrf: Callable[[Request], Awaitable[bool]] | None = None,
    verify_submission: Callable[[Request], Awaitable[bool]] | None = None,
    issue_submission: Callable[[Request], str] | None = None,
) -> Starlette:
    route, compiled = _compiled_page(definition)

    async def authorize(
        _request: Request, compiled_page: CompiledPageDefinition
    ) -> OperationAuthorization | None:
        return _authorization(compiled_page.permission, str(definition.page_id))

    binding = PageBinding(
        routes=((route, compiled),),
        templates=build_templates(()),
        authorize_page=authorize,
        verify_csrf=verify_csrf,
        verify_submission_token=verify_submission,
        issue_submission_token=issue_submission,
        idempotency_store=store,
        label="Operations",
    )
    return Starlette(routes=build_page_routes(binding))


def _client(app: Starlette) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://localhost")


@pytest.mark.anyio
async def test_read_only_page_parses_typed_query_and_executes_handler() -> None:
    seen: list[tuple[int, str]] = []

    async def handler(context: PageContext) -> PageResult[dict[str, int]]:
        assert isinstance(context.values, _ReadInput)
        assert context.authorization is not None
        assert context.principal is None
        seen.append((context.values.limit, context.authorization.operation))
        return PageResult(payload={"limit": context.values.limit}, message="Loaded")

    definition = PageDefinition(
        page_id="report",
        path="/reports",
        label="Report",
        input_schema=_ReadInput,
        handler=DomainPageHandler(handler),
    )
    async with _client(_app(definition)) as client:
        response = await client.get("/reports?limit=3")
        invalid = await client.get("/reports?limit=99")

    assert response.status_code == 200
    assert "Loaded" in response.text
    assert seen == [(3, "page:report")]
    assert invalid.status_code == 422


@pytest.mark.anyio
async def test_static_read_only_page_renders_without_handler() -> None:
    definition = PageDefinition(page_id="about", path="/about", label="About")
    async with _client(_app(definition)) as client:
        response = await client.get("/about")

    assert response.status_code == 200
    assert "About" in response.text
    assert "No page content was returned" in response.text


@pytest.mark.anyio
async def test_mutating_get_never_executes_handler() -> None:
    calls: list[str] = []

    async def handler(_context: PageContext) -> PageRedirect:
        calls.append("executed")
        return PageRedirect("/reports")

    definition = PageDefinition(
        page_id="rebuild",
        path="/rebuild",
        label="Rebuild",
        input_schema=_WriteInput,
        handler=DomainPageHandler(handler),
        mutating=True,
        transaction_policy=TransactionPolicy.DISABLED,
    )
    store = _MemoryIdempotencyStore()

    async def allowed(_request: Request) -> bool:
        return True

    async with _client(
        _app(
            definition,
            store=store,
            verify_csrf=allowed,
            verify_submission=allowed,
            issue_submission=lambda _request: "token",
        )
    ) as client:
        response = await client.get("/rebuild")

    assert response.status_code == 200
    assert calls == []
    assert store.begin_calls == 0


@pytest.mark.anyio
async def test_mutating_post_validates_input_before_reserving() -> None:
    calls: list[str] = []
    store = _MemoryIdempotencyStore()

    async def handler(_context: PageContext) -> PageRedirect:
        calls.append("executed")
        return PageRedirect("/reports")

    async def allowed(_request: Request) -> bool:
        return True

    definition = PageDefinition(
        page_id="rebuild",
        path="/rebuild",
        label="Rebuild",
        input_schema=_WriteInput,
        handler=DomainPageHandler(handler),
        mutating=True,
        transaction_policy=TransactionPolicy.DISABLED,
    )
    async with _client(
        _app(
            definition,
            store=store,
            verify_csrf=allowed,
            verify_submission=allowed,
            issue_submission=lambda _request: "token",
        )
    ) as client:
        response = await client.post(
            "/rebuild",
            data={"reason": "", "csrf_token": "csrf", "submission_token": "token"},
        )

    assert response.status_code == 422
    assert calls == []
    assert store.begin_calls == 0


@pytest.mark.anyio
async def test_mutating_page_redirect_replays_without_rerunning_handler() -> None:
    calls: list[str] = []
    store = _MemoryIdempotencyStore()

    async def handler(context: PageContext) -> PageRedirect:
        assert isinstance(context.values, _WriteInput)
        calls.append(context.values.reason)
        return PageRedirect("/reports", message="Queued")

    async def allowed(_request: Request) -> bool:
        return True

    definition = PageDefinition(
        page_id="rebuild",
        path="/rebuild",
        label="Rebuild",
        input_schema=_WriteInput,
        handler=DomainPageHandler(handler),
        mutating=True,
        transaction_policy=TransactionPolicy.DISABLED,
    )
    async with _client(
        _app(
            definition,
            store=store,
            verify_csrf=allowed,
            verify_submission=allowed,
            issue_submission=lambda _request: "token",
        )
    ) as client:
        payload = {"reason": "refresh", "csrf_token": "csrf", "submission_token": "token"}
        first = await client.post("/rebuild", data=payload, follow_redirects=False)
        second = await client.post("/rebuild", data=payload, follow_redirects=False)

    assert first.status_code == 303
    assert first.headers["location"] == "/reports"
    assert second.status_code == 303
    assert second.headers["location"] == "/reports"
    assert calls == ["refresh"]
    assert store.begin_calls == 2


@pytest.mark.anyio
async def test_page_rejection_releases_reservation_for_retry() -> None:
    calls = 0
    store = _MemoryIdempotencyStore()

    async def handler(_context: PageContext) -> PageRejected | PageRedirect:
        nonlocal calls
        calls += 1
        if calls == 1:
            return PageRejected(errors={"reason": "Busy"}, message="Try again")
        return PageRedirect("/reports")

    async def allowed(_request: Request) -> bool:
        return True

    definition = PageDefinition(
        page_id="rebuild",
        path="/rebuild",
        label="Rebuild",
        input_schema=_WriteInput,
        handler=DomainPageHandler(handler),
        mutating=True,
        transaction_policy=TransactionPolicy.DISABLED,
    )
    async with _client(
        _app(
            definition,
            store=store,
            verify_csrf=allowed,
            verify_submission=allowed,
            issue_submission=lambda _request: "token",
        )
    ) as client:
        payload = {"reason": "retry", "csrf_token": "csrf", "submission_token": "token"}
        rejected = await client.post("/rebuild", data=payload, follow_redirects=False)
        retried = await client.post("/rebuild", data=payload, follow_redirects=False)

    assert rejected.status_code == 409
    assert "Try again" in rejected.text
    assert retried.status_code == 303
    assert calls == 2
    assert store.release_calls == 1


@pytest.mark.anyio
async def test_execution_failure_terminalizes_submission() -> None:
    calls = 0
    store = _MemoryIdempotencyStore()

    async def handler(_context: PageContext) -> PageRedirect:
        nonlocal calls
        calls += 1
        raise RuntimeError("post-commit shaped failure")

    async def allowed(_request: Request) -> bool:
        return True

    definition = PageDefinition(
        page_id="rebuild",
        path="/rebuild",
        label="Rebuild",
        input_schema=_WriteInput,
        handler=DomainPageHandler(handler),
        mutating=True,
        transaction_policy=TransactionPolicy.DISABLED,
    )
    app = _app(
        definition,
        store=store,
        verify_csrf=allowed,
        verify_submission=allowed,
        issue_submission=lambda _request: "token",
    )
    payload = {"reason": "fail", "csrf_token": "csrf", "submission_token": "token"}
    async with _client(app) as client:
        with pytest.raises(RuntimeError, match="post-commit"):
            await client.post("/rebuild", data=payload)
        duplicate = await client.post("/rebuild", data=payload, follow_redirects=False)

    assert duplicate.status_code == 409
    assert calls == 1
    assert store.fail_final_calls == 1


@pytest.mark.anyio
async def test_mutating_page_rendered_result_fails_closed_after_execution() -> None:
    store = _MemoryIdempotencyStore()

    async def handler(_context: PageContext) -> PageResult[dict[str, bool]]:
        return PageResult(payload={"not_prg": True})

    async def allowed(_request: Request) -> bool:
        return True

    definition = PageDefinition(
        page_id="rebuild",
        path="/rebuild",
        label="Rebuild",
        input_schema=_WriteInput,
        handler=DomainPageHandler(handler),
        mutating=True,
        transaction_policy=TransactionPolicy.DISABLED,
    )
    async with _client(
        _app(
            definition,
            store=store,
            verify_csrf=allowed,
            verify_submission=allowed,
            issue_submission=lambda _request: "token",
        )
    ) as client:
        with pytest.raises(RakitError) as caught:
            await client.post(
                "/rebuild",
                data={"reason": "bad", "csrf_token": "csrf", "submission_token": "token"},
            )

    assert caught.value.details["reason"] == "post_redirect_required"
    assert store.fail_final_calls == 1
