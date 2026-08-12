from dataclasses import replace

import httpx
import pytest
from rakit_core.fields import FieldDefinition
from rakit_core.forms import FormSchema
from rakit_core.idempotency import IdempotencyReservation, IdempotencyStatus, OperationReceipt
from rakit_core.identity import RecordIdentity
from rakit_core.mutations import MutationAuthorization, MutationOperation
from rakit_web.form_routes import WriteResourceBinding, build_write_routes
from rakit_web.resource_routes import build_templates
from starlette.applications import Starlette


class FakeMutationService:
    def __init__(self) -> None:
        self.calls = 0

    async def create(
        self, submitted: dict[str, object], *, authorization: MutationAuthorization | None = None
    ) -> object:
        self.calls += 1
        return submitted


class FullFakeMutationService(FakeMutationService):
    def __init__(self) -> None:
        super().__init__()
        self.updated: tuple[RecordIdentity, dict[str, object], str | None] | None = None
        self.deleted: tuple[str, RecordIdentity] | None = None
        self.record = type("Record", (), {"name": "Ada"})()

    async def get(self, identity: RecordIdentity) -> object | None:
        return self.record if identity.values == {"id": 1} else None

    def issue_update_token(self, record: object) -> str:
        assert record is self.record
        return "revision-token"

    async def update(
        self,
        identity: RecordIdentity,
        submitted: dict[str, object],
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
        self, submitted: dict[str, object], *, authorization: MutationAuthorization | None = None
    ) -> object:
        import asyncio

        await asyncio.sleep(0.05)
        return await super().create(submitted, authorization=authorization)


class ContextCapturingMutationService(FakeMutationService):
    def __init__(self) -> None:
        super().__init__()
        self.operation_context: object | None = None

    async def create(
        self, submitted: dict[str, object], *, authorization: MutationAuthorization | None = None
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
    assert service.updated == (
        RecordIdentity(values={"id": 1}),
        {"name": "Grace"},
        "revision-token",
    )
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
