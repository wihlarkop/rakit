from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from typing import Any, cast
from uuid import UUID

import pytest
from rakit_core.errors import ErrorCode, RakitError
from rakit_core.identity import RecordIdentity
from rakit_core.query import Filter, FilterOperator, ResourceQuery
from rakit_sqlalchemy.datasource import SQLAlchemyDataSource
from sqlalchemy import Boolean, DateTime, Float, Integer, Numeric, String, Uuid
from sqlalchemy import Enum as SQLAlchemyEnum
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.types import TypeDecorator


class Base(DeclarativeBase):
    pass


class Status(Enum):
    ACTIVE = "active"
    DISABLED = "disabled"


class AliasedStatus(Enum):
    ACTIVE = "active"
    ENABLED = "active"
    DISABLED = "disabled"


class HexInteger(TypeDecorator[int]):
    impl = Integer
    cache_ok = True

    def rakit_coerce_filter_value(self, value: str) -> int:
        return int(value, 16)


class TypedRecord(Base):
    __tablename__ = "typed_records"

    id: Mapped[int] = mapped_column(primary_key=True)
    ratio: Mapped[float] = mapped_column(Float)
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    enabled: Mapped[bool] = mapped_column(Boolean)
    born_on: Mapped[date]
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    local_at: Mapped[datetime] = mapped_column(DateTime(timezone=False))
    external_id: Mapped[UUID] = mapped_column(Uuid)
    status: Mapped[Status] = mapped_column(SQLAlchemyEnum(Status))
    aliased_status: Mapped[AliasedStatus] = mapped_column(
        SQLAlchemyEnum(AliasedStatus, omit_aliases=False)
    )
    value_status: Mapped[Status] = mapped_column(
        SQLAlchemyEnum(Status, values_callable=lambda enum: [member.value for member in enum])
    )
    name: Mapped[str] = mapped_column(String)
    custom_number: Mapped[int] = mapped_column(HexInteger)


class StringRecord(Base):
    __tablename__ = "string_records"

    id: Mapped[str] = mapped_column(primary_key=True)


class UUIDRecord(Base):
    __tablename__ = "uuid_records"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)


class SessionFactorySpy:
    def __init__(self) -> None:
        self.calls = 0

    def __call__(self) -> Any:
        self.calls += 1
        raise AssertionError("invalid filters must fail before session creation")


def _datasource(session_factory: object | None = None) -> SQLAlchemyDataSource:
    factory = session_factory or SessionFactorySpy()
    return SQLAlchemyDataSource(
        model=TypedRecord,
        session_factory=cast(Any, factory),
    )


def _query(*filters: Filter) -> ResourceQuery:
    return ResourceQuery.from_params(
        allowed_sort_fields=set(TypedRecord.__table__.columns.keys()),
        identity_fields=("id",),
        filters=filters,
    )


def _bound_params(query: ResourceQuery) -> dict[str, object]:
    compiled = _compile(query)
    return dict(compiled.params)


def _compile(query: ResourceQuery) -> Any:
    statement = _datasource()._filtered_statement(query)
    return statement.compile(dialect=postgresql.dialect())


def _detail_bound_value(model: type[object], raw: int | str | UUID) -> object:
    datasource = SQLAlchemyDataSource(
        model=model,
        session_factory=cast(Any, SessionFactorySpy()),
    )
    statement = datasource._detail_statement(RecordIdentity(values={"id": raw}))
    compiled = statement.compile(dialect=postgresql.dialect())
    assert len(compiled.params) == 1
    return next(iter(compiled.params.values()))


def _single_bound_value(field: str, operator: FilterOperator, value: object) -> object:
    params = _bound_params(_query(Filter(field=field, operator=operator, value=value)))
    assert len(params) == 1
    return next(iter(params.values()))


def test_integer_filter_is_converted_before_strict_backend_binding() -> None:
    value = _single_bound_value("id", FilterOperator.GTE, "1")

    assert value == 1
    assert type(value) is int


@pytest.mark.parametrize(
    ("field", "raw", "expected"),
    [
        ("ratio", "1.25", 1.25),
        ("amount", "1234.50", Decimal("1234.50")),
        ("born_on", "2026-07-22", date(2026, 7, 22)),
        (
            "observed_at",
            "2026-07-22T14:30:45+07:00",
            datetime.fromisoformat("2026-07-22T14:30:45+07:00"),
        ),
        ("local_at", "2026-07-22T14:30:45", datetime(2026, 7, 22, 14, 30, 45)),
        (
            "external_id",
            "12345678-1234-5678-1234-567812345678",
            UUID("12345678-1234-5678-1234-567812345678"),
        ),
        ("status", "ACTIVE", Status.ACTIVE),
        ("aliased_status", "ACTIVE", AliasedStatus.ACTIVE),
        ("aliased_status", "ENABLED", AliasedStatus.ENABLED),
        ("value_status", "active", Status.ACTIVE),
        ("name", "Ada", "Ada"),
        ("custom_number", "ff", 255),
    ],
)
def test_scalar_filter_values_use_mapped_field_converter(
    field: str, raw: str, expected: object
) -> None:
    value = _single_bound_value(field, FilterOperator.EQ, raw)

    assert value == expected
    assert type(value) is type(expected)


@pytest.mark.parametrize(("raw", "expected"), [("TrUe", True), ("FALSE", False)])
def test_boolean_filter_accepts_only_case_insensitive_true_false(raw: str, expected: bool) -> None:
    query = _query(Filter(field="enabled", operator=FilterOperator.EQ, value=raw))
    compiled = _compile(query)

    assert compiled.params == {}
    assert f"typed_records.enabled = {str(expected).lower()}" in str(compiled)


@pytest.mark.parametrize(
    ("field", "raw"),
    [
        ("id", "not-an-integer"),
        ("enabled", "1"),
        ("enabled", "yes"),
        ("born_on", "22/07/2026"),
        ("observed_at", "2026-07-22T14:30:45"),
        ("local_at", "2026-07-22T14:30:45+07:00"),
        ("external_id", "not-a-uuid"),
        ("status", "UNKNOWN"),
    ],
)
async def test_invalid_scalar_is_stable_client_error_before_session_creation(
    field: str, raw: str
) -> None:
    factory = SessionFactorySpy()
    datasource = _datasource(factory)
    query = _query(Filter(field=field, operator=FilterOperator.EQ, value=raw))

    with pytest.raises(RakitError) as exc_info:
        await datasource.list(query)

    assert exc_info.value.code == ErrorCode.VALIDATION_FAILED
    assert exc_info.value.status_code == 400
    assert exc_info.value.to_public_dict() == {
        "code": "validation.failed",
        "message": "Invalid filter value",
        "details": {"field": field, "operator": "eq"},
    }
    assert factory.calls == 0


def test_in_converts_each_item_without_mutating_input_query() -> None:
    raw_values = ["1", "2"]
    query = _query(Filter(field="id", operator=FilterOperator.IN, value=raw_values))
    before = query.model_dump(mode="python")

    params = _bound_params(query)

    assert next(iter(params.values())) == [1, 2]
    assert query.model_dump(mode="python") == before
    assert query.filters[0].value == ("1", "2")
    assert query.filters[0].value is not raw_values


def test_multiple_filters_use_field_specific_converters() -> None:
    query = _query(
        Filter(field="id", operator=FilterOperator.GTE, value="1"),
        Filter(field="enabled", operator=FilterOperator.EQ, value="false"),
        Filter(field="amount", operator=FilterOperator.LT, value="10.25"),
        Filter(field="name", operator=FilterOperator.NEQ, value="root"),
    )

    params = _bound_params(query)

    assert params == {
        "id_1": 1,
        "amount_1": Decimal("10.25"),
        "name_1": "root",
    }
    assert "typed_records.enabled = false" in str(_compile(query))


async def test_contains_rejects_non_string_column_before_session_creation() -> None:
    factory = SessionFactorySpy()
    datasource = _datasource(factory)
    query = _query(Filter(field="id", operator=FilterOperator.CONTAINS, value="1"))

    with pytest.raises(RakitError) as exc_info:
        await datasource.list(query)

    assert exc_info.value.to_public_dict() == {
        "code": "validation.failed",
        "message": "Filter operator is not valid for this field",
        "details": {"field": "id", "operator": "contains"},
    }
    assert factory.calls == 0


def test_is_null_keeps_existing_boolean_semantics_without_bound_value() -> None:
    query = _query(Filter(field="name", operator=FilterOperator.IS_NULL, value=True))

    statement = _datasource()._filtered_statement(query)
    compiled = statement.compile(dialect=postgresql.dialect())

    assert compiled.params == {}
    assert "typed_records.name IS NULL" in str(compiled)


@pytest.mark.parametrize(
    ("model", "raw", "expected"),
    [
        (TypedRecord, "42", 42),
        (StringRecord, "record-42", "record-42"),
        (
            UUIDRecord,
            UUID("a0ebc21a-7334-4ab2-8f01-01e5af6d8a24"),
            UUID("a0ebc21a-7334-4ab2-8f01-01e5af6d8a24"),
        ),
    ],
)
def test_detail_identity_uses_mapped_type_before_strict_backend_binding(
    model: type[object], raw: int | str | UUID, expected: object
) -> None:
    value = _detail_bound_value(model, raw)

    assert value == expected
    assert type(value) is type(expected)


@pytest.mark.parametrize(
    "identity",
    (
        RecordIdentity(values={"id": "not-a-uuid"}),
        RecordIdentity(values={"wrong_field": "a0ebc21a-7334-4ab2-8f01-01e5af6d8a24"}),
    ),
)
async def test_invalid_detail_identity_is_safe_before_session_creation(
    identity: RecordIdentity,
) -> None:
    factory = SessionFactorySpy()
    datasource = SQLAlchemyDataSource(
        model=UUIDRecord,
        session_factory=cast(Any, factory),
    )

    with pytest.raises(RakitError) as exc_info:
        await datasource.detail(identity)

    assert exc_info.value.to_public_dict() == {
        "code": "validation.failed",
        "message": "Invalid resource identity",
        "details": {"field": "id"},
    }
    assert factory.calls == 0


def test_free_text_search_excludes_sqlalchemy_enum_on_strict_dialect() -> None:
    statement = _datasource()._filtered_statement(
        ResourceQuery.from_params(
            allowed_sort_fields=set(TypedRecord.__table__.columns.keys()),
            identity_fields=("id",),
            search="active",
        )
    )

    sql = str(statement.compile(dialect=postgresql.dialect()))

    assert sql.count(" LIKE ") == 1
    assert "typed_records.name LIKE" in sql
    assert "typed_records.status LIKE" not in sql
