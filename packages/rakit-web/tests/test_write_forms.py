import httpx
import pytest
from rakit_core.fields import FieldDefinition
from rakit_core.forms import FormSchema
from rakit_web.form_routes import WriteResourceBinding, build_write_routes
from rakit_web.resource_routes import build_templates
from starlette.applications import Starlette


class FakeMutationService:
    def __init__(self) -> None:
        self.calls = 0

    async def create(self, submitted: dict[str, object]) -> object:
        self.calls += 1
        return submitted


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
