from collections.abc import Mapping
from dataclasses import replace
from datetime import date
from typing import cast

import httpx
import pytest
from rakit_core.auth import Principal
from rakit_core.di import ServiceRegistry, ServiceScope
from rakit_core.events import EventBus, EventPublisher
from rakit_core.fields import FieldDefinition
from rakit_core.forms import (
    CollapsibleGroup,
    FieldLayout,
    FormLayout,
    FormSchema,
    FormState,
    Tab,
    Tabs,
)
from rakit_core.idempotency import IdempotencyReservation, IdempotencyStatus, OperationReceipt
from rakit_core.identity import RecordIdentity
from rakit_core.mutations import MutationAuthorization, MutationOperation
from rakit_core.operations import OperationContext
from rakit_sqlalchemy.mutations import SQLAlchemyMutationService
from rakit_web.form_routes import WriteResourceBinding, build_write_routes
from rakit_web.resource_routes import build_templates
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.middleware.base import BaseHTTPMiddleware


class FakeRecord:
    def __init__(self, name: str = "Ada", password_hash: str | None = None) -> None:
        self.name = name
        self.password_hash = password_hash


class ParsedBase(DeclarativeBase):
    pass


class ParsedRecord(ParsedBase):
    __tablename__ = "parsed_records"

    id: Mapped[int] = mapped_column(primary_key=True)
    day: Mapped[date]


class _PrincipalMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        request.scope.setdefault("state", {})["principal"] = Principal(
            subject_id="tester",
            authenticated=True,
            permissions=frozenset({"admin.resources.parsed-records.create"}),
        )
        return await call_next(request)


class FakeMutationService:
    def __init__(self) -> None:
        self.calls = 0

    async def create(
        self, submitted: Mapping[str, object], *, authorization: MutationAuthorization | None = None
    ) -> object:
        self.calls += 1
        return submitted


class FullFakeMutationService(FakeMutationService):
    def __init__(self) -> None:
        super().__init__()
        self.updated: tuple[RecordIdentity, Mapping[str, object], str | None] | None = None
        self.deleted: tuple[str, RecordIdentity] | None = None
        self.record: object = FakeRecord()

    async def get(self, identity: RecordIdentity) -> object | None:
        return self.record if identity.values == {"id": 1} else None

    def issue_update_token(self, record: object) -> str:
        assert record is self.record
        return "revision-token"

    async def update(
        self,
        identity: RecordIdentity,
        submitted: Mapping[str, object],
        *,
        concurrency_token: str | None,
        authorization: MutationAuthorization | None = None,
    ) -> object:
        self.updated = (identity, submitted, concurrency_token)
        return self.record

    async def issue_delete_token(self, identity: RecordIdentity) -> str:
        assert identity.values == {"id": 1}
        return "delete-token"

    async def delete(
        self,
        confirmation_token: str,
        *,
        identity: RecordIdentity,
        authorization: MutationAuthorization | None = None,
    ) -> None:
        self.deleted = (confirmation_token, identity)


class SlowMutationService(FakeMutationService):
    async def create(
        self, submitted: Mapping[str, object], *, authorization: MutationAuthorization | None = None
    ) -> object:
        import asyncio

        await asyncio.sleep(0.05)
        return await super().create(submitted, authorization=authorization)


class ContextCapturingMutationService(FakeMutationService):
    def __init__(self) -> None:
        super().__init__()
        self.operation_context: object | None = None

    async def create(
        self, submitted: Mapping[str, object], *, authorization: MutationAuthorization | None = None
    ) -> object:
        from rakit_core.operations import current_operation_context

        self.operation_context = current_operation_context()
        return await super().create(submitted, authorization=authorization)


class FakeIdempotencyStore:
    def __init__(self) -> None:
        self._claims: dict[str, tuple[str, OperationReceipt | None]] = {}

    async def begin(self, token_hash: str, *, fingerprint: str) -> IdempotencyReservation:
        claim = self._claims.get(token_hash)
        if claim is None:
            self._claims[token_hash] = (fingerprint, None)
            return IdempotencyReservation(1, IdempotencyStatus.IN_PROGRESS)
        if claim[0] != fingerprint:
            from rakit_core.errors import ErrorCode, RakitError

            raise RakitError(
                code=ErrorCode.VALIDATION_FAILED,
                message="Submission token does not match this request.",
                status_code=400,
            )
        if claim[1] is not None:
            return IdempotencyReservation(1, IdempotencyStatus.COMPLETED, claim[1], False)
        return IdempotencyReservation(1, IdempotencyStatus.IN_PROGRESS, claimed=False)

    async def complete(
        self, reservation: IdempotencyReservation, receipt: OperationReceipt
    ) -> None:
        for token, (fingerprint, _receipt) in self._claims.items():
            self._claims[token] = (fingerprint, receipt)

    async def release(self, reservation: IdempotencyReservation) -> None:
        self._claims.clear()

    async def fail_final(self, reservation: IdempotencyReservation) -> None:
        return None


async def _allow(_request: object) -> bool:
    return True


async def _allow_mutation(
    _request: object, operation: MutationOperation, _identity: RecordIdentity | None
) -> MutationAuthorization:
    return MutationAuthorization(
        admin_id="admin",
        resource_id="/users",
        operation=operation,
        principal_id="tester",
        permissions=(f"admin.resources.users.{operation}",),
    )


@pytest.mark.anyio
async def test_invalid_form_returns_accessible_422() -> None:
    binding = WriteResourceBinding(
        path="/users",
        label="User",
        form_schema=FormSchema(
            fields=(FieldDefinition(field_id="email", python_type=str, required=True),)
        ),
        mutation_service=FakeMutationService(),
        templates=build_templates(()),
        authorize=_allow,
        verify_csrf=_allow,
        verify_submission_token=_allow,
        issue_submission_token=lambda _request: "submission",
        mutation_authorizer=_allow_mutation,
    )
    app = Starlette(routes=build_write_routes(binding))
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://localhost") as client:
        response = await client.post("/users/new", data={"email": "", "csrf_token": "x"})

    assert response.status_code == 422
    assert 'aria-invalid="true"' in response.text
    assert 'data-rakit-focus-target="form-errors"' in response.text


@pytest.mark.anyio
async def test_invalid_submission_token_is_rejected_before_mutation() -> None:
    service = FakeMutationService()

    async def reject_submission(_request: object) -> bool:
        return False

    binding = WriteResourceBinding(
        path="/users",
        label="User",
        form_schema=FormSchema(
            fields=(FieldDefinition(field_id="email", python_type=str, required=True),)
        ),
        mutation_service=service,
        templates=build_templates(()),
        authorize=_allow,
        verify_csrf=_allow,
        verify_submission_token=reject_submission,
        issue_submission_token=lambda _request: "submission",
        mutation_authorizer=_allow_mutation,
    )
    app = Starlette(routes=build_write_routes(binding))
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://localhost") as client:
        response = await client.post(
            "/users/new",
            data={"email": "ada@example.com", "csrf_token": "x", "submission_token": "bad"},
        )

    assert response.status_code == 409
    assert service.calls == 0


@pytest.mark.anyio
async def test_update_and_delete_routes_bind_identity_tokens_and_mount_prefix() -> None:
    service = FullFakeMutationService()
    binding = WriteResourceBinding(
        path="/users",
        label="User",
        form_schema=FormSchema(
            fields=(FieldDefinition(field_id="name", python_type=str, required=True),)
        ),
        mutation_service=service,
        templates=build_templates(()),
        authorize=_allow,
        verify_csrf=_allow,
        verify_submission_token=_allow,
        issue_submission_token=lambda _request: "submission",
        mutation_authorizer=_allow_mutation,
    )
    encoded = binding.codec.encode(RecordIdentity(values={"id": 1}))
    app = Starlette(routes=build_write_routes(binding))
    transport = httpx.ASGITransport(app=app, root_path="/admin")
    async with httpx.AsyncClient(transport=transport, base_url="http://localhost") as client:
        edit = await client.get(f"/users/{encoded}/edit")
        assert edit.status_code == 200
        assert 'value="Ada"' in edit.text
        assert 'name="concurrency_token" value="revision-token"' in edit.text
        assert f'action="/admin/users/{encoded}/edit"' in edit.text

        updated = await client.post(
            f"/users/{encoded}/edit",
            data={
                "name": "Grace",
                "csrf_token": "csrf",
                "submission_token": "submission",
                "concurrency_token": "revision-token",
            },
            follow_redirects=False,
        )
        assert updated.status_code == 303
        delete = await client.get(f"/users/{encoded}/delete")
        assert delete.status_code == 200
        assert 'name="delete_token" value="delete-token"' in delete.text
        assert f'action="/admin/users/{encoded}/delete"' in delete.text

        deleted = await client.post(
            f"/users/{encoded}/delete",
            data={"csrf_token": "csrf", "delete_token": "delete-token"},
            follow_redirects=False,
        )
    assert deleted.status_code == 303
    assert service.updated is not None
    assert service.updated[0] == RecordIdentity(values={"id": 1})
    assert isinstance(service.updated[1], FormState)
    assert dict(service.updated[1].normalized) == {"name": "Grace"}
    assert service.updated[2] == "revision-token"
    assert service.deleted == ("delete-token", RecordIdentity(values={"id": 1}))


@pytest.mark.anyio
async def test_mutation_deadline_returns_504_before_the_service_completes() -> None:
    service = SlowMutationService()
    binding = WriteResourceBinding(
        path="/users",
        label="User",
        form_schema=FormSchema(
            fields=(FieldDefinition(field_id="email", python_type=str, required=True),)
        ),
        mutation_service=service,
        templates=build_templates(()),
        authorize=_allow,
        verify_csrf=_allow,
        verify_submission_token=_allow,
        issue_submission_token=lambda _request: "submission",
        mutation_authorizer=_allow_mutation,
        deadline_seconds=0.001,
    )
    app = Starlette(routes=build_write_routes(binding))
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://localhost") as client:
        response = await client.post(
            "/users/new",
            data={"email": "ada@example.com", "csrf_token": "x", "submission_token": "x"},
        )
    assert response.status_code == 504
    assert service.calls == 0


@pytest.mark.anyio
async def test_idempotent_create_replays_without_second_mutation() -> None:
    service = FakeMutationService()
    binding = WriteResourceBinding(
        path="/users",
        label="User",
        form_schema=FormSchema(
            fields=(FieldDefinition(field_id="email", python_type=str, required=True),)
        ),
        mutation_service=service,
        templates=build_templates(()),
        authorize=_allow,
        verify_csrf=_allow,
        verify_submission_token=_allow,
        issue_submission_token=lambda _request: "submission",
        mutation_authorizer=_allow_mutation,
        idempotency_store=FakeIdempotencyStore(),
    )
    app = Starlette(routes=build_write_routes(binding))
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://localhost") as client:
        payload = {"email": "ada@example.com", "csrf_token": "x", "submission_token": "same"}
        first = await client.post("/users/new", data=payload, follow_redirects=False)
        second = await client.post("/users/new", data=payload, follow_redirects=False)
        mismatch = await client.post(
            "/users/new",
            data={**payload, "email": "grace@example.com"},
            follow_redirects=False,
        )
    assert first.status_code == 303
    assert second.status_code == 303
    assert mismatch.status_code == 400
    assert service.calls == 1


@pytest.mark.anyio
async def test_request_deadline_is_visible_to_the_mutation_pipeline() -> None:
    service = ContextCapturingMutationService()
    operation_events = EventPublisher(EventBus())
    registry = ServiceRegistry()
    registry.add_value(object, service, scope=ServiceScope.APPLICATION)
    async with (
        registry.application_scope() as application,
        application.request_scope() as request_services,
    ):
        binding = WriteResourceBinding(
            path="/users",
            label="User",
            form_schema=FormSchema(
                fields=(FieldDefinition(field_id="email", python_type=str, required=True),)
            ),
            mutation_service=service,
            templates=build_templates(()),
            authorize=_allow,
            verify_csrf=_allow,
            verify_submission_token=_allow,
            issue_submission_token=lambda _request: "submission",
            mutation_authorizer=_allow_mutation,
            deadline_seconds=1,
            operation_scope=request_services.operation_scope,
            event_publisher=operation_events,
        )
        app = Starlette(routes=build_write_routes(binding))
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://localhost") as client:
            response = await client.post(
                "/users/new",
                data={"email": "ada@example.com", "csrf_token": "x", "submission_token": "x"},
                follow_redirects=False,
            )
    assert response.status_code == 303
    assert service.operation_context is not None
    context = cast(OperationContext, service.operation_context)
    assert context.services is not None and context.services.require(object) is service
    assert context.events is operation_events


@pytest.mark.anyio
async def test_timed_out_idempotent_submission_releases_its_claim_for_retry() -> None:
    service = SlowMutationService()
    store = FakeIdempotencyStore()
    binding = WriteResourceBinding(
        path="/users",
        label="User",
        form_schema=FormSchema(
            fields=(FieldDefinition(field_id="email", python_type=str, required=True),)
        ),
        mutation_service=service,
        templates=build_templates(()),
        authorize=_allow,
        verify_csrf=_allow,
        verify_submission_token=_allow,
        issue_submission_token=lambda _request: "submission",
        mutation_authorizer=_allow_mutation,
        deadline_seconds=0.001,
        idempotency_store=store,
    )
    app = Starlette(routes=build_write_routes(binding))
    transport = httpx.ASGITransport(app=app)
    payload = {"email": "ada@example.com", "csrf_token": "x", "submission_token": "same"}
    async with httpx.AsyncClient(transport=transport, base_url="http://localhost") as client:
        timed_out = await client.post("/users/new", data=payload)
        retry_binding = replace(binding, deadline_seconds=1)
        retry_app = Starlette(routes=build_write_routes(retry_binding))
        retry = await httpx.AsyncClient(
            transport=httpx.ASGITransport(app=retry_app), base_url="http://localhost"
        ).post("/users/new", data=payload, follow_redirects=False)
    assert timed_out.status_code == 504
    assert retry.status_code == 303
    assert service.calls == 1


@pytest.mark.anyio
async def test_invalid_layout_form_links_errors_and_opens_invalid_tab() -> None:
    binding = WriteResourceBinding(
        path="/users",
        label="User",
        form_schema=FormSchema(
            fields=(
                FieldDefinition(
                    field_id="email",
                    python_type=str,
                    required=True,
                    description="We use this for notifications.",
                ),
            ),
            layout=FormLayout(
                children=(
                    Tabs(
                        layout_id="profile-tabs",
                        tabs=(
                            Tab(
                                layout_id="contact",
                                label="Contact",
                                children=(
                                    CollapsibleGroup(
                                        layout_id="contact-details",
                                        label="Details",
                                        children=(FieldLayout("email"),),
                                    ),
                                ),
                            ),
                        ),
                    ),
                )
            ),
        ),
        mutation_service=FakeMutationService(),
        templates=build_templates(()),
        authorize=_allow,
        verify_csrf=_allow,
        verify_submission_token=_allow,
        issue_submission_token=lambda _request: "submission",
        mutation_authorizer=_allow_mutation,
    )
    app = Starlette(routes=build_write_routes(binding))
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://localhost"
    ) as client:
        response = await client.post("/users/new", data={"email": "", "csrf_token": "x"})

    assert response.status_code == 422
    assert 'for="rakit--users-email"' in response.text
    assert 'id="rakit--users-email"' in response.text
    assert 'aria-invalid="true"' in response.text
    assert (
        'aria-describedby="rakit--users-email-description rakit--users-email-error"'
        in response.text
    )
    assert 'href="#rakit--users-email"' in response.text
    assert 'data-rakit-first-invalid="rakit--users-email"' in response.text
    assert 'aria-selected="true"' in response.text
    assert "(1)</span>" in response.text
    assert 'id="contact-details" open' in response.text
    assert 'href="#contact"' in response.text
    assert 'id="contact" role="tabpanel" hidden' not in response.text


@pytest.mark.anyio
async def test_parser_normalizes_before_idempotency_fingerprint_and_htmx_result_is_semantic() -> (
    None
):
    service = FakeMutationService()
    binding = WriteResourceBinding(
        path="/users",
        label="User",
        form_schema=FormSchema(
            fields=(
                FieldDefinition(
                    field_id="name",
                    python_type=str,
                    required=True,
                    parser=lambda value: str(value).strip().lower(),
                ),
            )
        ),
        mutation_service=service,
        templates=build_templates(()),
        authorize=_allow,
        verify_csrf=_allow,
        verify_submission_token=_allow,
        issue_submission_token=lambda _request: "submission",
        mutation_authorizer=_allow_mutation,
        idempotency_store=FakeIdempotencyStore(),
        htmx_refresh_targets=("resource-list",),
        success_message="Saved",
    )
    app = Starlette(routes=build_write_routes(binding))
    payload = {"name": " Ada ", "csrf_token": "x", "submission_token": "same"}
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://localhost"
    ) as client:
        first = await client.post("/users/new", data=payload, headers={"HX-Request": "true"})
        second = await client.post(
            "/users/new",
            data={**payload, "name": "ada"},
            headers={"HX-Request": "true"},
        )

    assert first.status_code == 204
    assert "HX-Redirect" not in first.headers
    assert "rakit:refresh" in first.headers["HX-Trigger"]
    assert "rakit:toast" in first.headers["HX-Trigger"]
    assert second.status_code == 204
    assert service.calls == 1


@pytest.mark.anyio
async def test_update_formatter_is_used_but_sensitive_field_is_never_rendered() -> None:
    service = FullFakeMutationService()
    service.record = FakeRecord(password_hash="private")
    binding = WriteResourceBinding(
        path="/users",
        label="User",
        form_schema=FormSchema(
            fields=(
                FieldDefinition(
                    field_id="name",
                    python_type=str,
                    required=True,
                    formatter=lambda value: f"User: {value}",
                ),
                FieldDefinition(
                    field_id="password_hash",
                    python_type=str,
                    formatter=lambda _value: "leaked",
                ),
            )
        ),
        mutation_service=service,
        templates=build_templates(()),
        authorize=_allow,
        verify_csrf=_allow,
        verify_submission_token=_allow,
        issue_submission_token=lambda _request: "submission",
        mutation_authorizer=_allow_mutation,
    )
    encoded = binding.codec.encode(RecordIdentity(values={"id": 1}))
    app = Starlette(routes=build_write_routes(binding))
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://localhost"
    ) as client:
        response = await client.get(f"/users/{encoded}/edit")

    assert 'value="User: Ada"' in response.text
    assert "password_hash" not in response.text
    assert "leaked" not in response.text


@pytest.mark.anyio
async def test_web_to_sqlalchemy_parses_custom_field_once_before_execution() -> None:
    calls = 0

    def parse_day(value: object) -> date:
        nonlocal calls
        calls += 1
        if not isinstance(value, str):
            raise ValueError("transport input must be text")
        return date.fromisoformat(value)

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(ParsedBase.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    schema = FormSchema(
        fields=(FieldDefinition(field_id="day", python_type=date, parser=parse_day),)
    )
    service = SQLAlchemyMutationService(
        model=ParsedRecord,
        session_factory=factory,
        form_schema=schema,
        writable_fields=("day",),
        identity_fields=("id",),
        resource_id="parsed-records",
    )

    async def authorize_mutation(
        _request: object, operation: MutationOperation, _identity: RecordIdentity | None
    ) -> MutationAuthorization:
        return MutationAuthorization(
            admin_id="admin",
            resource_id="parsed-records",
            operation=operation,
            principal_id="tester",
            permissions=("admin.resources.parsed-records.create",),
        )

    binding = WriteResourceBinding(
        path="/parsed-records",
        label="Parsed record",
        form_schema=schema,
        mutation_service=service,
        templates=build_templates(()),
        authorize=_allow,
        verify_csrf=_allow,
        verify_submission_token=_allow,
        issue_submission_token=lambda _request: "submission",
        mutation_authorizer=authorize_mutation,
        deadline_seconds=5,
    )
    app = Starlette(
        routes=build_write_routes(binding), middleware=[Middleware(_PrincipalMiddleware)]
    )

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://localhost"
    ) as client:
        response = await client.post(
            "/parsed-records/new",
            data={"day": "2026-08-12", "csrf_token": "x", "submission_token": "x"},
            follow_redirects=False,
        )
    async with factory() as session:
        persisted = (await session.execute(select(ParsedRecord))).scalar_one()
    await engine.dispose()

    assert response.status_code == 303
    assert calls == 1
    assert persisted.day == date(2026, 8, 12)
