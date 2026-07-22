from collections.abc import AsyncIterator
from enum import Enum as PythonEnum

import pytest
from rakit_core.definitions import ResourceFieldPolicy
from rakit_core.errors import ErrorCode, RakitError
from rakit_core.identity import RecordIdentity
from rakit_core.query import (
    Filter,
    FilterOperator,
    NullPlacement,
    ResourceQuery,
    Sort,
    SortDirection,
)
from rakit_sqlalchemy.datasource import SQLAlchemyDataSource
from rakit_sqlalchemy.introspection import UnsupportedFieldPolicyError
from rakit_sqlalchemy.plugin import SQLAlchemyPlugin
from sqlalchemy import Enum as SQLAlchemyEnum
from sqlalchemy import LargeBinary, String
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.types import TypeDecorator


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str]
    password_hash: Mapped[str | None] = mapped_column(nullable=True)


class Status(PythonEnum):
    ACTIVE = "active"
    DISABLED = "disabled"


class Article(Base):
    """A model with a non-string, non-filterable field for policy-semantics
    tests: `status` is an Enum (unsearchable, but filterable via the typed
    filter path); `payload` is a `LargeBinary` (neither searchable nor
    filterable -- no built-in coercion path exists for it)."""

    __tablename__ = "articles"

    id: Mapped[int] = mapped_column(primary_key=True)
    views: Mapped[int]
    status: Mapped[Status] = mapped_column(SQLAlchemyEnum(Status))
    payload: Mapped[bytes] = mapped_column(LargeBinary)


class MalformedHookType(TypeDecorator):
    """A `TypeDecorator` declaring `rakit_coerce_filter_value` as a non-`None`
    but non-callable attribute -- a malformed adapter contract that must be
    rejected at claim/registration time, not merely "present" and trusted."""

    impl = String
    cache_ok = True
    rakit_coerce_filter_value = object()


class MalformedHookRecord(Base):
    __tablename__ = "malformed_hook_records"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(MalformedHookType)


USER_POLICY = ResourceFieldPolicy(
    list_fields=("id", "name"),
    detail_fields=("id", "name"),
    filter_fields=("id", "name"),
    search_fields=("name",),
    sort_fields=("id", "name"),
)


@pytest.fixture
async def session_factory() -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    factory = async_sessionmaker(engine, expire_on_commit=False)

    async with factory() as session:
        session.add_all([User(id=1, name="Ada"), User(id=2, name="Grace")])
        await session.commit()

    yield factory

    await engine.dispose()


async def test_sqlalchemy_datasource_lists_and_loads(session_factory) -> None:
    datasource = SQLAlchemyDataSource(
        model=User, session_factory=session_factory, field_policy=USER_POLICY
    )
    page = await datasource.list(
        ResourceQuery.from_params(
            sort="name",
            allowed_sort_fields={"id", "name"},
            identity_fields=("id",),
        )
    )
    record = await datasource.detail(RecordIdentity(values={"id": 1}))
    assert [item.name for item in page.items] == ["Ada", "Grace"]
    assert isinstance(record, User)
    assert record.name == "Ada"
    assert page.total_count == 2
    assert page.has_previous is False
    assert page.has_next is False


async def test_sqlalchemy_datasource_applies_eq_filter(session_factory) -> None:
    datasource = SQLAlchemyDataSource(
        model=User, session_factory=session_factory, field_policy=USER_POLICY
    )
    page = await datasource.list(
        ResourceQuery.from_params(
            sort="name",
            allowed_sort_fields={"id", "name"},
            identity_fields=("id",),
            filters=(Filter(field="name", operator=FilterOperator.EQ, value="Ada"),),
        )
    )
    assert [item.name for item in page.items] == ["Ada"]
    assert page.total_count == 1


async def test_sqlalchemy_datasource_detail_not_found_returns_none(session_factory) -> None:
    datasource = SQLAlchemyDataSource(
        model=User, session_factory=session_factory, field_policy=USER_POLICY
    )
    record = await datasource.detail(RecordIdentity(values={"id": 999}))
    assert record is None


async def test_sqlalchemy_datasource_pagination(session_factory) -> None:
    datasource = SQLAlchemyDataSource(
        model=User, session_factory=session_factory, field_policy=USER_POLICY
    )
    page = await datasource.list(
        ResourceQuery.from_params(
            sort="name",
            allowed_sort_fields={"id", "name"},
            identity_fields=("id",),
            page=1,
            per_page=1,
        )
    )
    assert [item.name for item in page.items] == ["Ada"]
    assert page.total_count == 2
    assert page.has_previous is False
    assert page.has_next is True

    second_page = await datasource.list(
        ResourceQuery.from_params(
            sort="name",
            allowed_sort_fields={"id", "name"},
            identity_fields=("id",),
            page=2,
            per_page=1,
        )
    )
    assert [item.name for item in second_page.items] == ["Grace"]
    assert second_page.has_previous is True
    assert second_page.has_next is False


@pytest.mark.parametrize(
    "query",
    (
        ResourceQuery(filters=(Filter(field="name", operator=FilterOperator.EQ, value="Ada"),)),
        ResourceQuery(sorting=(Sort(field="name"),)),
        ResourceQuery(search="Ada"),
    ),
)
async def test_sqlalchemy_datasource_rejects_direct_query_policy_bypass(
    session_factory,
    query: ResourceQuery,
) -> None:
    datasource = SQLAlchemyDataSource(
        model=User,
        session_factory=session_factory,
        field_policy=ResourceFieldPolicy(
            list_fields=("id", "name"),
            detail_fields=("id", "name"),
        ),
    )

    with pytest.raises(RakitError) as exc_info:
        await datasource.list(query)

    assert exc_info.value.to_public_dict() == {
        "code": "validation.failed",
        "message": "Query field is not allowed",
    }


async def test_direct_identity_sort_requires_explicit_policy(session_factory) -> None:
    datasource = SQLAlchemyDataSource(
        model=User,
        session_factory=session_factory,
        field_policy=ResourceFieldPolicy(
            list_fields=("id", "name"),
            detail_fields=("id", "name"),
        ),
    )

    with pytest.raises(RakitError) as exc_info:
        await datasource.list(
            ResourceQuery(sorting=(Sort(field="id", direction=SortDirection.DESC),))
        )

    assert exc_info.value.to_public_dict() == {
        "code": "validation.failed",
        "message": "Query field is not allowed",
    }


async def test_direct_identity_sort_is_allowed_when_explicitly_declared(session_factory) -> None:
    datasource = SQLAlchemyDataSource(
        model=User,
        session_factory=session_factory,
        field_policy=ResourceFieldPolicy(
            list_fields=("id", "name"),
            detail_fields=("id", "name"),
            sort_fields=("id",),
        ),
    )

    page = await datasource.list(
        ResourceQuery(sorting=(Sort(field="id", direction=SortDirection.DESC),))
    )

    assert [item.id for item in page.items] == [2, 1]


async def test_internal_identity_tie_breaker_is_appended_exactly_once(session_factory) -> None:
    datasource = SQLAlchemyDataSource(
        model=User,
        session_factory=session_factory,
        field_policy=USER_POLICY,
    )

    sorting = datasource._effective_sorting(
        ResourceQuery(sorting=(Sort(field="name"), Sort(field="id")))
    )

    assert [sort.field for sort in sorting] == ["name", "id"]


async def test_from_params_identity_tie_breaker_composes_with_narrower_sort_policy(
    session_factory,
) -> None:
    """Regression for the reconciliation between `ResourceQuery.from_params()`'s
    public `identity_fields` composition and a datasource's `sort_fields`
    policy: the identity field need not itself be user-sortable for
    `identity_fields=("id",)` to keep working, because it is recorded as an
    `identity_tie_breakers` entry rather than folded into the validated
    `sorting` list."""
    datasource = SQLAlchemyDataSource(
        model=User,
        session_factory=session_factory,
        field_policy=ResourceFieldPolicy(
            list_fields=("id", "name"),
            detail_fields=("id", "name"),
            sort_fields=("name",),
        ),
    )
    query = ResourceQuery.from_params(
        sort="name",
        allowed_sort_fields={"name"},
        identity_fields=("id",),
    )

    # Accepted despite "id" being outside `sort_fields` -- it never reaches
    # `sorting`, only `identity_tie_breakers`, which is exempt from that check.
    page = await datasource.list(query)
    assert [item.name for item in page.items] == ["Ada", "Grace"]

    # The adapter still appends stable identity ordering after explicit
    # sorting: name first (the explicit, user-requested sort), then id.
    effective = datasource._effective_sorting(query)
    assert [(sort.field, sort.direction) for sort in effective] == [
        ("name", SortDirection.ASC),
        ("id", SortDirection.ASC),
    ]

    # A *separately constructed*, explicit user sort on "id" must still be
    # rejected -- this fix must not reopen the policy bypass fixed in de5dec5.
    with pytest.raises(RakitError) as exc_info:
        await datasource.list(ResourceQuery(sorting=(Sort(field="id"),)))
    assert exc_info.value.to_public_dict() == {
        "code": "validation.failed",
        "message": "Query field is not allowed",
    }


async def test_real_identity_tie_breaker_is_accepted(session_factory) -> None:
    datasource = SQLAlchemyDataSource(
        model=User, session_factory=session_factory, field_policy=USER_POLICY
    )

    page = await datasource.list(
        ResourceQuery(sorting=(Sort(field="name"),), identity_tie_breakers=(Sort(field="id"),))
    )

    assert [item.name for item in page.items] == ["Ada", "Grace"]


@pytest.mark.parametrize(
    "identity_tie_breakers",
    (
        # Not this datasource's identity field, but a real (sensitive) column.
        (Sort(field="password_hash"),),
        # A real, ordinary, non-identity column.
        (Sort(field="name"),),
        # The real identity field, but not ascending.
        (Sort(field="id", direction=SortDirection.DESC),),
        # The real identity field, but with an explicit null-placement override.
        (Sort(field="id", nulls=NullPlacement.FIRST),),
        (Sort(field="id", nulls=NullPlacement.LAST),),
        # The real identity field, named twice.
        (Sort(field="id"), Sort(field="id")),
    ),
)
async def test_identity_tie_breakers_restricted_to_canonical_identity_shape(
    session_factory,
    identity_tie_breakers: tuple[Sort, ...],
) -> None:
    """`identity_tie_breakers` is exempt from the `sort_fields` whitelist, but
    that exemption must not mean "any known field" -- only this datasource's
    actual identity field(s), ascending, with default null placement, named
    at most once, may appear there. Anything else (a sensitive column, an
    ordinary non-identity column, a non-ascending direction, an explicit null
    placement, or a duplicate) is rejected exactly like an unknown query
    field."""
    datasource = SQLAlchemyDataSource(
        model=User, session_factory=session_factory, field_policy=USER_POLICY
    )

    with pytest.raises(RakitError) as exc_info:
        await datasource.list(
            ResourceQuery(
                sorting=(Sort(field="name"),),
                identity_tie_breakers=identity_tie_breakers,
            )
        )

    assert exc_info.value.to_public_dict() == {
        "code": "validation.failed",
        "message": "Query field is not allowed",
    }


@pytest.mark.parametrize(
    "search_fields",
    (
        ("views",),
        ("status",),
        ("payload",),
        ("views", "status"),
    ),
)
async def test_unsupported_search_fields_fail_before_registration(
    session_factory,
    search_fields: tuple[str, ...],
) -> None:
    """A declared search field that this adapter cannot actually search on
    (integer, Enum, or binary) must fail closed at construction/claim time --
    it must never silently no-op and turn `?search=...` into an unfiltered
    full-table scan."""
    with pytest.raises(UnsupportedFieldPolicyError):
        SQLAlchemyDataSource(
            model=Article,
            session_factory=session_factory,
            field_policy=ResourceFieldPolicy(
                list_fields=("id",),
                detail_fields=("id",),
                search_fields=search_fields,
            ),
        )


async def test_mixed_valid_and_invalid_search_fields_are_wholly_rejected(
    session_factory,
) -> None:
    """A mix of a valid string field and an invalid one must reject the whole
    policy -- not silently search only the valid field."""
    with pytest.raises(UnsupportedFieldPolicyError) as exc_info:
        SQLAlchemyDataSource(
            model=User,
            session_factory=session_factory,
            field_policy=ResourceFieldPolicy(
                list_fields=("id", "name"),
                detail_fields=("id", "name"),
                search_fields=("name", "id"),
            ),
        )
    assert exc_info.value.field == "id"
    assert exc_info.value.policy == "search_fields"


async def test_string_only_search_fields_remain_valid(session_factory) -> None:
    datasource = SQLAlchemyDataSource(
        model=User,
        session_factory=session_factory,
        field_policy=ResourceFieldPolicy(
            list_fields=("id", "name"),
            detail_fields=("id", "name"),
            search_fields=("name",),
        ),
    )
    page = await datasource.list(ResourceQuery(search="Ada"))
    assert [item.name for item in page.items] == ["Ada"]


async def test_resource_without_search_fields_remains_valid(session_factory) -> None:
    datasource = SQLAlchemyDataSource(
        model=User,
        session_factory=session_factory,
        field_policy=ResourceFieldPolicy(list_fields=("id", "name"), detail_fields=("id", "name")),
    )
    page = await datasource.list(ResourceQuery())
    assert len(page.items) == 2


async def test_unsupported_filter_field_fails_before_registration(session_factory) -> None:
    """`filter_fields` gets the same fail-closed treatment: a field whose
    mapped type has no coercion path (e.g. `LargeBinary`) must reject the
    resource's compiled policy rather than waiting for the first request
    that tries to filter on it."""
    with pytest.raises(UnsupportedFieldPolicyError) as exc_info:
        SQLAlchemyDataSource(
            model=Article,
            session_factory=session_factory,
            field_policy=ResourceFieldPolicy(
                list_fields=("id",),
                detail_fields=("id",),
                filter_fields=("payload",),
            ),
        )
    assert exc_info.value.field == "payload"
    assert exc_info.value.policy == "filter_fields"


async def test_malformed_filter_hook_fails_before_registration(session_factory) -> None:
    """A type declaring `rakit_coerce_filter_value` as a non-`None` but
    non-callable attribute is a malformed adapter contract -- it must be
    rejected at claim/registration time (fail-closed), not accepted merely
    because the attribute is present, only to fail on the first request that
    actually tries to filter on it."""
    with pytest.raises(UnsupportedFieldPolicyError) as exc_info:
        SQLAlchemyDataSource(
            model=MalformedHookRecord,
            session_factory=session_factory,
            field_policy=ResourceFieldPolicy(
                list_fields=("id",),
                detail_fields=("id",),
                filter_fields=("code",),
            ),
        )
    assert exc_info.value.field == "code"
    assert exc_info.value.policy == "filter_fields"


async def test_enum_filter_field_remains_valid_despite_being_unsearchable(
    session_factory,
) -> None:
    """Enum is unconditionally unsupported for search (its persisted string
    has no stable case mapping back to a member), but remains a supported
    *filter* field via the existing typed-filter Enum path."""
    datasource = SQLAlchemyDataSource(
        model=Article,
        session_factory=session_factory,
        field_policy=ResourceFieldPolicy(
            list_fields=("id",),
            detail_fields=("id",),
            filter_fields=("status",),
        ),
    )
    assert isinstance(datasource, SQLAlchemyDataSource)


async def test_claim_rejects_unsupported_search_field_with_stable_error(session_factory) -> None:
    """The claim boundary (what `rakit check`/compilation exercises before any
    request is served) must surface the same failure as a stable, non-leaking
    `RakitError` -- not a raw adapter exception."""
    plugin = SQLAlchemyPlugin(session_factory=session_factory)
    policy = ResourceFieldPolicy(
        list_fields=("id",),
        detail_fields=("id",),
        search_fields=("views",),
    )

    with pytest.raises(RakitError) as exc_info:
        plugin._claim(Article, policy)

    assert exc_info.value.code == ErrorCode.CONFIG_UNSUPPORTED_FIELD_POLICY
    assert exc_info.value.details == {
        "model": "Article",
        "field": "views",
        "policy": "search_fields",
    }
    # The public error must not leak database column names, SQL, or values.
    public = exc_info.value.to_public_dict()
    assert "SELECT" not in str(public)
    assert "articles" not in str(public)


async def test_claim_rejects_malformed_filter_hook_with_stable_error(session_factory) -> None:
    plugin = SQLAlchemyPlugin(session_factory=session_factory)
    policy = ResourceFieldPolicy(
        list_fields=("id",),
        detail_fields=("id",),
        filter_fields=("code",),
    )

    with pytest.raises(RakitError) as exc_info:
        plugin._claim(MalformedHookRecord, policy)

    assert exc_info.value.code == ErrorCode.CONFIG_UNSUPPORTED_FIELD_POLICY
    assert exc_info.value.details == {
        "model": "MalformedHookRecord",
        "field": "code",
        "policy": "filter_fields",
    }
