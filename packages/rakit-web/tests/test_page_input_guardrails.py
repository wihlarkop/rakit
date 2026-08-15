"""Task 6 trust-boundary regression tests for custom Page input."""

import httpx
import pytest
from pydantic import BaseModel
from rakit_core.compiler import ApplicationBuilder, compile_application
from rakit_core.definitions import CompiledPageDefinition, PageDefinition
from rakit_core.idempotency import (
    IdempotencyReservation,
    IdempotencyStatus,
    OperationReceipt,
)
from rakit_core.mutations import OperationAuthorization
from rakit_core.pages import DomainPageHandler, PageContext, PageRedirect, PageResult
from rakit_core.transactions import TransactionPolicy
from rakit_web.page_routes import PageBinding, build_page_routes
from rakit_web.resource_routes import build_templates
from starlette.applications import Starlette
from starlette.requests import Request


class _Input(BaseModel):
    limit: int


class _Store:
    production_safe = True

    def __init__(self) -> None:
        self.begin_calls = 0

    async def begin(self, token_hash: str, *, fingerprint: str) -> IdempotencyReservation:
        del token_hash, fingerprint
        self.begin_calls += 1
        return IdempotencyReservation(1, IdempotencyStatus.IN_PROGRESS)

    async def complete(
        self, reservation: IdempotencyReservation, receipt: OperationReceipt
    ) -> None:
        del reservation, receipt

    async def release(self, reservation: IdempotencyReservation) -> None:
        del reservation

    async def fail_final(self, reservation: IdempotencyReservation) -> None:
        del reservation


def _app(definition: PageDefinition, store: _Store | None = None) -> Starlette:
    builder = ApplicationBuilder(admin_id="ops")
    builder.add_page(definition)
    compiled = compile_application(builder)
    route = next(
        route for route in compiled.routes if route.route_name == f"page:{definition.page_id}"
    )
    compiled_page = compiled.compiled_pages[0]

    async def authorize(
        _request: Request, _compiled_page: CompiledPageDefinition
    ) -> OperationAuthorization:
        return OperationAuthorization.for_requirement(
            admin_id="ops",
            resource_id=str(definition.page_id),
            operation=f"page:{definition.page_id}",
            principal_id="operator",
            requirement=compiled_page.permission,
        )

    async def verify_csrf_like_admin(request: Request) -> bool:
        # The real Admin CSRF verifier may parse the form before Page parsing.
        # This intentionally exercises the cached-form path for file rejection.
        await request.form()
        return True

    async def verify_submission(_request: Request) -> bool:
        return True

    binding = PageBinding(
        routes=((route, compiled_page),),
        templates=build_templates(()),
        authorize_page=authorize,
        verify_csrf=verify_csrf_like_admin if definition.mutating else None,
        verify_submission_token=verify_submission if definition.mutating else None,
        issue_submission_token=(lambda _request: "token") if definition.mutating else None,
        idempotency_store=store,
    )
    return Starlette(routes=build_page_routes(binding))


@pytest.mark.anyio
async def test_read_page_rejects_unknown_query_field_before_handler() -> None:
    calls: list[int] = []

    async def handler(context: PageContext) -> PageResult[None]:
        assert isinstance(context.values, _Input)
        calls.append(context.values.limit)
        return PageResult()

    definition = PageDefinition(
        page_id="report",
        path="/reports",
        label="Report",
        input_schema=_Input,
        handler=DomainPageHandler(handler),
    )
    app = _app(definition)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://localhost"
    ) as client:
        response = await client.get("/reports?limit=3&admin=true")

    assert response.status_code == 422
    assert "Unknown page input field" in response.text
    assert calls == []


@pytest.mark.anyio
async def test_mutating_page_rejects_unknown_field_before_idempotency() -> None:
    calls: list[str] = []
    store = _Store()

    async def handler(_context: PageContext) -> PageRedirect:
        calls.append("executed")
        return PageRedirect("/reports")

    definition = PageDefinition(
        page_id="rebuild",
        path="/rebuild",
        label="Rebuild",
        input_schema=_Input,
        handler=DomainPageHandler(handler),
        mutating=True,
        transaction_policy=TransactionPolicy.DISABLED,
    )
    app = _app(definition, store)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://localhost"
    ) as client:
        response = await client.post(
            "/rebuild",
            data={
                "limit": "3",
                "unexpected": "1",
                "csrf_token": "csrf",
                "submission_token": "token",
            },
        )

    assert response.status_code == 422
    assert calls == []
    assert store.begin_calls == 0


@pytest.mark.anyio
async def test_mutating_page_rejects_file_even_when_csrf_already_parsed_form() -> None:
    calls: list[str] = []
    store = _Store()

    async def handler(_context: PageContext) -> PageRedirect:
        calls.append("executed")
        return PageRedirect("/reports")

    definition = PageDefinition(
        page_id="rebuild",
        path="/rebuild",
        label="Rebuild",
        input_schema=_Input,
        handler=DomainPageHandler(handler),
        mutating=True,
        transaction_policy=TransactionPolicy.DISABLED,
    )
    app = _app(definition, store)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://localhost"
    ) as client:
        response = await client.post(
            "/rebuild",
            data={"limit": "3", "csrf_token": "csrf", "submission_token": "token"},
            files={"attachment": ("note.txt", b"not allowed", "text/plain")},
        )

    assert response.status_code == 422
    assert "File uploads are not supported" in response.text
    assert calls == []
    assert store.begin_calls == 0
