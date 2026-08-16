import pytest
from rakit_core.fields import FileField


def test_file_field_is_non_queryable_and_uses_file_widget() -> None:
    field = FileField(
        field_id="attachment",
        storage_id="documents",
        allowed_extensions=(".PDF", ".txt"),
        allowed_mime_types=("application/pdf", "text/plain"),
        delete_behavior="delete",
    )

    assert field.python_type is dict
    assert field.widget == "file"
    assert field.storage_id == "documents"
    assert field.allowed_extensions == (".pdf", ".txt")
    assert field.allowed_mime_types == ("application/pdf", "text/plain")
    assert field.delete_behavior == "delete"
    assert field.readable is True
    assert field.writable is True
    assert field.searchable is False
    assert field.filterable is False
    assert field.sortable is False


def test_file_field_has_private_safe_defaults() -> None:
    field = FileField(field_id="attachment", storage_id="documents")

    assert field.max_size == 10 * 1024 * 1024
    assert field.max_filename_length == 255
    assert field.allow_empty is False
    assert field.delete_behavior == "keep"
    assert field.prefix is None


def test_file_field_rejects_unsafe_policy() -> None:
    with pytest.raises(ValueError):
        FileField(field_id="attachment", storage_id="")
    with pytest.raises(ValueError):
        FileField(field_id="attachment", storage_id="../documents")
    with pytest.raises(ValueError):
        FileField(field_id="attachment", storage_id="documents", max_size=0)
    with pytest.raises(ValueError):
        FileField(field_id="attachment", storage_id="documents", max_filename_length=0)
    with pytest.raises(ValueError):
        FileField(field_id="attachment", storage_id="documents", prefix="../outside")
    with pytest.raises(ValueError):
        FileField(field_id="attachment", storage_id="documents", allowed_extensions=("pdf",))
    with pytest.raises(ValueError):
        FileField(field_id="attachment", storage_id="documents", allowed_extensions=("../pdf",))
    with pytest.raises(ValueError):
        FileField(field_id="attachment", storage_id="documents", allowed_mime_types=("",))
    with pytest.raises(ValueError):
        FileField(field_id="attachment", storage_id="documents", delete_behavior="sometimes")
