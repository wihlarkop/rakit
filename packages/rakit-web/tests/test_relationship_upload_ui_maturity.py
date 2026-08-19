from collections.abc import Mapping
from hashlib import sha256
from pathlib import Path

import httpx
import pytest
from rakit_core.fields import FileField
from rakit_core.forms import FormSchema
from rakit_core.identity import RecordIdentity
from rakit_core.mutations import MutationAuthorization, MutationOperation
from rakit_core.relationships import (
    RelationshipCardinality,
    RelationshipDefinition,
    RelationshipEditMode,
    RelationshipKind,
)
from rakit_storage import StoredFile
from rakit_web.file_presentation import file_field_presentation
from rakit_web.form_routes import WriteResourceBinding, build_write_routes
from rakit_web.relationship_routes import _relationship_presentation_mode
from rakit_web.resource_routes import build_templates
from starlette.applications import Starlette
from starlette.requests import Request


class _FileService:
    def __init__(self, record: Mapping[str, object]) -> None:
        self.record = dict(record)

    async def create(
        self,
        submitted: Mapping[str, object],
        *,
        authorization: MutationAuthorization | None = None,
    ) -> object:
        del authorization
        self.record = dict(submitted)
        return self.record

    async def get(self, identity: RecordIdentity) -> object | None:
        del identity
        return self.record

    def issue_update_token(self, record: object) -> str:
        del record
        return "update-token"

    async def update(
        self,
        identity: RecordIdentity,
        submitted: Mapping[str, object],
        *,
        concurrency_token: str | None,
        authorization: MutationAuthorization | None = None,
    ) -> object:
        del identity, concurrency_token, authorization
        self.record = dict(submitted)
        return self.record

    async def issue_delete_token(self, identity: RecordIdentity) -> str:
        del identity
        return "delete-token"

    async def delete(
        self,
        confirmation_token: str,
        *,
        identity: RecordIdentity,
        authorization: MutationAuthorization | None = None,
    ) -> None:
        del confirmation_token, identity, authorization


async def _allow(_request: Request) -> bool:
    return True


async def _authorize(
    _request: Request,
    operation: MutationOperation,
    identity: RecordIdentity | None,
) -> MutationAuthorization:
    return MutationAuthorization(
        admin_id="admin",
        resource_id="documents",
        operation=operation,
        principal_id="tester",
        permissions=(f"admin.resources.documents.{operation}",),
        target_identity=identity,
    )


def _file_field() -> FileField:
    return FileField(
        field_id="attachment",
        storage_id="documents",
        required=True,
        max_size=2 * 1024 * 1024,
        max_filename_length=120,
        allowed_extensions=(".pdf", ".txt"),
        allowed_mime_types=("application/pdf", "text/plain"),
    )


def _stored_file() -> StoredFile:
    payload = b"existing-pdf"
    return StoredFile(
        storage_id="documents",
        key="private/internal/existing.pdf",
        original_name="customer-contract.pdf",
        content_type="application/pdf",
        size=len(payload),
        checksum=f"sha256:{sha256(payload).hexdigest()}",
    )


def _relationship(
    *,
    cardinality: RelationshipCardinality = RelationshipCardinality.TO_MANY,
    edit_mode: RelationshipEditMode = RelationshipEditMode.LINK,
) -> RelationshipDefinition:
    return RelationshipDefinition(
        relationship_id="people",
        target_resource_id="people",
        label="People",
        kind=(
            RelationshipKind.MANY_TO_ONE
            if cardinality is RelationshipCardinality.TO_ONE
            else RelationshipKind.MANY_TO_MANY
        ),
        cardinality=cardinality,
        writable=True,
        nullable=cardinality is RelationshipCardinality.TO_ONE,
        edit_mode=edit_mode,
        record_label_field="name",
    )


def test_relationship_presentation_is_result_driven() -> None:
    linked = _relationship()
    assert (
        _relationship_presentation_mode(
            definition=linked,
            has_previous=False,
            has_next=False,
        )
        == "compact"
    )
    assert (
        _relationship_presentation_mode(
            definition=linked,
            has_previous=False,
            has_next=True,
        )
        == "paginated"
    )
    assert (
        _relationship_presentation_mode(
            definition=_relationship(edit_mode=RelationshipEditMode.INLINE),
            has_previous=True,
            has_next=True,
        )
        == "inline"
    )
    assert (
        _relationship_presentation_mode(
            definition=_relationship(edit_mode=RelationshipEditMode.NESTED),
            has_previous=True,
            has_next=True,
        )
        == "inline"
    )
    assert (
        _relationship_presentation_mode(
            definition=_relationship(cardinality=RelationshipCardinality.TO_ONE),
            has_previous=True,
            has_next=True,
        )
        == "to_one"
    )


def test_file_presentation_exposes_policy_not_storage_internals() -> None:
    stored = _stored_file()
    presentation = file_field_presentation(_file_field(), stored)

    assert presentation.accept == ".pdf,.txt,application/pdf,text/plain"
    assert "PDF" in presentation.policy_hint
    assert "TXT" in presentation.policy_hint
    assert "Maximum size: 2 MB" in presentation.policy_hint
    assert "up to 120 characters" in presentation.policy_hint
    assert presentation.current is not None
    assert presentation.current.name == "customer-contract.pdf"
    assert presentation.current.content_type == "application/pdf"
    assert stored.key not in repr(presentation)
    assert stored.checksum not in repr(presentation)
    assert stored.storage_id not in repr(presentation)


@pytest.mark.anyio
async def test_edit_form_presents_current_file_as_replace_not_remove() -> None:
    stored = _stored_file()
    service = _FileService({"attachment": stored.model_dump(mode="python")})
    binding = WriteResourceBinding(
        path="/documents",
        resource_id="documents",
        label="Document",
        form_schema=FormSchema(fields=(_file_field(),)),
        mutation_service=service,
        templates=build_templates(()),
        authorize=_allow,
        verify_csrf=_allow,
        verify_submission_token=_allow,
        issue_submission_token=lambda _request: "submission",
        mutation_authorizer=_authorize,
    )
    encoded = binding.codec.encode(RecordIdentity(values={"id": "doc-1"}))
    app = Starlette(routes=build_write_routes(binding))

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await client.get(f"/documents/{encoded}/edit")

    assert response.status_code == 200
    assert "Current file" in response.text
    assert "customer-contract.pdf" in response.text
    assert "Maximum size: 2 MB" in response.text
    assert (
        "Choose a new file to replace the current file; leave this empty to keep it."
        in response.text
    )
    assert stored.key not in response.text
    assert stored.checksum not in response.text
    assert 'name="attachment"' in response.text
    assert 'name="attachment" required' not in response.text
    assert "Remove file" not in response.text
    assert "Clear file" not in response.text
    assert "Delete file" not in response.text


def test_relationship_templates_keep_native_mutation_controls() -> None:
    template_root = Path(__file__).parents[1] / "src" / "rakit_web" / "templates" / "relationships"
    panel = (template_root / "panel.html").read_text()
    inline = (template_root / "inline_rows.html").read_text()
    to_many = (template_root / "to_many.html").read_text()

    assert 'type="submit" formaction="{{ panel.page_path }}/page/' in panel
    assert 'type="submit" name="{{ panel.prefix }}move__{{ encoded }}__up"' in inline
    assert 'type="submit" name="{{ panel.prefix }}move__{{ encoded }}__down"' in inline
    assert 'data-rakit-unlink-input type="checkbox"' in inline
    assert "Remove from relationship" in inline
    assert "Delete record" in inline
    assert 'data-rakit-unlink-input type="checkbox"' in to_many
    assert "Remove from relationship" in to_many
    assert "Delete record" in to_many
