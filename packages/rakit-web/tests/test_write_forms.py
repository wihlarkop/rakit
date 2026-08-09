import httpx
import pytest
from rakit_core.fields import FieldDefinition
from rakit_core.forms import FormSchema
from rakit_core.identity import RecordIdentity
from rakit_web.form_routes import WriteResourceBinding, build_write_routes
from rakit_web.resource_routes import build_templates
from starlette.applications import Starlette


class FakeMutationService:
    def __init__(self) -> None:
        self.calls = 0

    async def create(self, submitted: dict[str, object]) -> object:
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
    ) -> object:
        self.updated = (identity, submitted, concurrency_token)
        return self.record

    async def issue_delete_token(self, identity: RecordIdentity) -> str:
        assert identity.values == {"id": 1}
        return "delete-token"

    async def delete(self, confirmation_token: str, *, identity: RecordIdentity) -> None:
        self.deleted = (confirmation_token, identity)


async def _allow(_request: object) -> bool:
    return True


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
