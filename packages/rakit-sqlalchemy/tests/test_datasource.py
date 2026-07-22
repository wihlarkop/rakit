from collections.abc import AsyncIterator

import pytest
from rakit_core.definitions import ResourceFieldPolicy
from rakit_core.errors import RakitError
from rakit_core.identity import RecordIdentity
from rakit_core.query import Filter, FilterOperator, ResourceQuery, Sort
from rakit_sqlalchemy.datasource import SQLAlchemyDataSource
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str]


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
