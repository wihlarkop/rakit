import pytest
from peewee import BlobField, ForeignKeyField, SqliteDatabase, TextField
from playhouse.pwasyncio import AsyncSqliteDatabase
from rakit_core.definitions import ResourceFieldPolicy
from rakit_peewee.introspection import (
    MismatchedPeeweeDatabaseError,
    UnsupportedPeeweeAsyncDatabaseError,
    UnsupportedPeeweeFieldPolicyError,
    inspect_model,
    validate_field_policy,
)


def test_peewee_introspection_accepts_async_models_and_keeps_relationships_out_of_scalar_fields(
) -> None:
    database = AsyncSqliteDatabase(":memory:")

    class Author(database.Model):
        name = TextField()

    class Book(database.Model):
        title = TextField()
        author = ForeignKeyField(Author)

    metadata = inspect_model(Book, database=database)

    assert metadata.identity_field == "id"
    assert metadata.field_names == ("id", "title")
    assert "author" not in metadata.field_names


def test_peewee_introspection_rejects_synchronous_database_models() -> None:
    database = SqliteDatabase(":memory:")

    class Widget(database.Model):
        name = TextField()

    with pytest.raises(UnsupportedPeeweeAsyncDatabaseError):
        inspect_model(Widget)


def test_peewee_introspection_rejects_model_bound_to_different_async_database() -> None:
    first = AsyncSqliteDatabase(":memory:")
    second = AsyncSqliteDatabase(":memory:")

    class Widget(first.Model):
        name = TextField()

    with pytest.raises(MismatchedPeeweeDatabaseError):
        inspect_model(Widget, database=second)


def test_peewee_field_policy_fails_closed_for_nonportable_fields() -> None:
    database = AsyncSqliteDatabase(":memory:")

    class Widget(database.Model):
        name = TextField()
        payload = BlobField()

    metadata = inspect_model(Widget, database=database)

    with pytest.raises(UnsupportedPeeweeFieldPolicyError) as captured:
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
