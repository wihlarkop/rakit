from collections.abc import AsyncIterator

import pytest
from rakit_core.query import (
    CountPolicy,
    Filter,
    FilterOperator,
    OffsetPagination,
    ResourceQuery,
)
from rakit_sqlalchemy.datasource import SQLAlchemyDataSource
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str]
    email: Mapped[str]


@pytest.fixture
async def datasource() -> AsyncIterator[SQLAlchemyDataSource]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    factory: async_sessionmaker[AsyncSession] = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        session.add_all(
            [
                User(id=1, name="Ada", email="ada@example.com"),
                User(id=2, name="Grace", email="grace@work.test"),
            ]
        )
        await session.commit()

    yield SQLAlchemyDataSource(model=User, session_factory=factory)
    await engine.dispose()


def _query(
    *,
    search: str | None = None,
    filters: tuple[Filter, ...] = (),
) -> ResourceQuery:
    return ResourceQuery.from_params(
        allowed_sort_fields={"id", "name", "email"},
        identity_fields=("id",),
        search=search,
        filters=filters,
    )


async def test_disabled_count_uses_limit_plus_one(datasource: SQLAlchemyDataSource) -> None:
    query = ResourceQuery(
        pagination=OffsetPagination(page=1, per_page=1),
        count_policy=CountPolicy.DISABLED,
    )
    page = await datasource.list(query)
    assert len(page.items) == 1
    assert page.has_next is True
    assert page.total_count is None


async def test_disabled_count_last_page_has_no_next(datasource: SQLAlchemyDataSource) -> None:
    query = ResourceQuery(
        pagination=OffsetPagination(page=2, per_page=1),
        count_policy=CountPolicy.DISABLED,
    )
    page = await datasource.list(query)
    assert len(page.items) == 1
    assert page.has_next is False
    assert page.has_previous is True
    assert page.total_count is None


async def test_deferred_count_defers_total(datasource: SQLAlchemyDataSource) -> None:
    query = ResourceQuery(
        pagination=OffsetPagination(page=1, per_page=1),
        count_policy=CountPolicy.DEFERRED,
    )
    page = await datasource.list(query)
    assert len(page.items) == 1
    assert page.has_next is True
    assert page.total_count is None


async def test_count_method_runs_exact_count(datasource: SQLAlchemyDataSource) -> None:
    total = await datasource.count(_query())
    assert total == 2


async def test_count_method_respects_filters(datasource: SQLAlchemyDataSource) -> None:
    total = await datasource.count(
        _query(filters=(Filter(field="name", operator=FilterOperator.EQ, value="Ada"),))
    )
    assert total == 1


async def test_search_matches_across_string_fields(datasource: SQLAlchemyDataSource) -> None:
    # "work" only appears in Grace's email, not her name -> search must span fields.
    page = await datasource.list(_query(search="work"))
    assert [item.name for item in page.items] == ["Grace"]
    assert page.total_count == 1


async def test_search_ignores_non_string_columns(datasource: SQLAlchemyDataSource) -> None:
    # "1" would match the integer id if search were applied to non-string columns;
    # since it is not present in any string field, the result must be empty.
    page = await datasource.list(_query(search="1"))
    assert page.items == ()
    assert page.total_count == 0


async def test_search_and_filter_combine(datasource: SQLAlchemyDataSource) -> None:
    page = await datasource.list(
        _query(
            search="example.com",
            filters=(Filter(field="name", operator=FilterOperator.EQ, value="Ada"),),
        )
    )
    assert [item.name for item in page.items] == ["Ada"]

    empty = await datasource.list(
        _query(
            search="example.com",
            filters=(Filter(field="name", operator=FilterOperator.EQ, value="Grace"),),
        )
    )
    assert empty.items == ()
