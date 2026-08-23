from pathlib import Path

import pytest
from piccolo.columns import Bytea, ForeignKey, Varchar
from piccolo.engine.sqlite import SQLiteEngine
from piccolo.table import Table
from rakit_core.definitions import ResourceFieldPolicy
from rakit_piccolo.introspection import (
    MismatchedPiccoloEngineError,
    UnsupportedPiccoloFieldPolicyError,
    inspect_model,
    validate_field_policy,
)


def test_piccolo_introspection_keeps_relationships_out_of_scalar_fields(tmp_path: Path) -> None:
    engine = SQLiteEngine(path=str(tmp_path / "relationships.sqlite3"))

    class Author(Table, db=engine):
        name = Varchar()

    class Book(Table, db=engine):
        title = Varchar()
        author = ForeignKey(references=Author)

    metadata = inspect_model(Book, engine=engine)

    assert metadata.identity_field == "id"
    assert metadata.field_names == ("id", "title")
    assert "author" not in metadata.field_names


def test_piccolo_introspection_rejects_model_bound_to_different_engine(tmp_path: Path) -> None:
    first = SQLiteEngine(path=str(tmp_path / "first.sqlite3"))
    second = SQLiteEngine(path=str(tmp_path / "second.sqlite3"))

    class Widget(Table, db=first):
        name = Varchar()

    with pytest.raises(MismatchedPiccoloEngineError):
        inspect_model(Widget, engine=second)


def test_piccolo_field_policy_fails_closed_for_nonportable_fields(tmp_path: Path) -> None:
    engine = SQLiteEngine(path=str(tmp_path / "payload.sqlite3"))

    class Widget(Table, db=engine):
        name = Varchar()
        payload = Bytea()

    metadata = inspect_model(Widget, engine=engine)

    with pytest.raises(UnsupportedPiccoloFieldPolicyError) as captured:
        validate_field_policy(
            metadata,
            ResourceFieldPolicy(
                list_fields=("id", "name", "payload"),
                detail_fields=("id", "name", "payload"),
                filter_fields=("payload",),
            ),
        )

    assert captured.value.field == "payload"
    assert captured.value.policy == "filter_fields"
