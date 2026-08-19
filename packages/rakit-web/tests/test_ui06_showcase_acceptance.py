import pytest
from rakit_core.identity import RecordIdentity
from rakit_core.relationships import RelationshipCardinality, RelationshipEditMode

from examples.ui_showcase.advanced_states import (
    _SEEDED_FILE,
    ADVANCED_LAUNCHERS,
    FILE_STORAGE,
    RELATIONSHIPS,
    _RelationshipStateProvider,
)
from examples.ui_showcase.main import admin, app


def test_ui06_acceptance_launchers_and_pages_are_compiled() -> None:
    launcher_paths = {launcher.path for launcher in ADVANCED_LAUNCHERS}
    assert launcher_paths == {
        "/relationship-states",
        "/acceptance-documents",
        "/acceptance-page-mapping",
    }

    compiled = admin.compiled
    assert compiled is not None
    compiled_page_ids = {str(page.definition.page_id) for page in compiled.compiled_pages}
    assert {
        "acceptance_page_scalar",
        "acceptance_page_mapping",
        "acceptance_page_table",
        "acceptance_page_empty",
        "acceptance_page_unsupported",
        "acceptance_page_mutation",
    } <= compiled_page_ids
    assert app is not None


def test_ui06_relationship_fixture_covers_required_presentation_states() -> None:
    by_id = {relationship.relationship_id: relationship for relationship in RELATIONSHIPS}

    assert by_id["customer"].cardinality is RelationshipCardinality.TO_ONE
    assert by_id["customer"].effective_writable is True
    assert by_id["participants"].cardinality is RelationshipCardinality.TO_MANY
    assert by_id["line_items"].edit_mode is RelationshipEditMode.INLINE
    assert by_id["line_items"].ordered is True
    assert by_id["large_order"].ordered is True
    assert by_id["read_only_team"].effective_writable is False
    assert by_id["unlink_only"].destructive_policy.allow_delete_orphan is False
    assert by_id["unlink_only"].destructive_policy.allow_destructive_cascade is False


@pytest.mark.anyio
async def test_ui06_relationship_runtime_state_drives_pagination_and_reorder_unavailable() -> None:
    provider = _RelationshipStateProvider()
    parent = RecordIdentity(values={"id": 1})

    selected_customer = await provider.editor_page(parent, "customer")
    empty_customer = await provider.editor_page(RecordIdentity(values={"id": 2}), "customer")
    participants = await provider.editor_page(parent, "participants")
    large_order = await provider.reorder_identities(parent, "large_order", maximum=2)

    assert len(selected_customer.items) == 1
    assert empty_customer.items == ()
    assert participants.has_next is True
    assert participants.total_count == 30
    assert large_order is None


def test_ui06_upload_fixture_uses_real_seeded_storage_descriptor() -> None:
    assert _SEEDED_FILE.storage_id == FILE_STORAGE.storage_id == "showcase-documents"
    assert _SEEDED_FILE.original_name == "current-contract.pdf"
    assert _SEEDED_FILE.content_type == "application/pdf"
    assert _SEEDED_FILE.key in FILE_STORAGE.objects
    assert FILE_STORAGE.objects[_SEEDED_FILE.key].startswith(b"%PDF-1.4")
    assert _SEEDED_FILE.checksum.startswith("sha256:")
