from collections.abc import AsyncIterator

import pytest
from rakit import Admin, ModelAdmin, TextFilter
from rakit_core.definitions import ResourceFieldPolicy
from rakit_core.errors import ErrorCode, RakitError
from rakit_core.pagination import (
    CursorPagination,
    LimitOffsetPagination,
    LimitOffsetResult,
    PagePagination,
    PageResult,
    PaginationStrategy,
)
from rakit_core.query import CountPolicy, Filter, FilterOperator, ResourceQuery
from rakit_sqlalchemy.datasource import SQLAlchemyDataSource
from rakit_sqlalchemy.plugin import SQLAlchemyPlugin
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Order(Base):
    __tablename__ = "query_configuration_orders"

    id: Mapped[int] = mapped_column(primary_key=True)
    status: Mapped[str]
    score: Mapped[int]


POLICY = ResourceFieldPolicy(
    list_fields=("id", "status", "score"),
    detail_fields=("id", "status", "score"),
    filter_fields=("status", "score"),
    sort_fields=("id", "status", "score"),
)


@pytest.fixture
async def datasource() -> AsyncIterator[SQLAlchemyDataSource]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    factory: async_sessionmaker[AsyncSession] = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        session.add_all(
            [
                Order(id=1, status="paid", score=10),
                Order(id=2, status="pending", score=20),
                Order(id=3, status="paid", score=30),
                Order(id=4, status="cancelled", score=40),
            ]
        )
        await session.commit()

    yield SQLAlchemyDataSource(model=Order, session_factory=factory, field_policy=POLICY)
    await engine.dispose()


def test_sqlalchemy_claims_only_page_and_limit_offset_capabilities() -> None:
    assert SQLAlchemyDataSource.capabilities.pagination_strategies == frozenset(
        {PaginationStrategy.PAGE, PaginationStrategy.LIMIT_OFFSET}
    )


async def test_first_class_filter_predicate_field_is_claimed_without_legacy_filter_fields() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    factory: async_sessionmaker[AsyncSession] = async_sessionmaker(engine, expire_on_commit=False)

    class OrdersAdmin(ModelAdmin):
        model = Order
        resource_id = "orders"
        path = "/orders"
        label = "Orders"
        singular_label = "Order"
        list_fields = ("id", "status")
        detail_fields = ("id", "status", "score")
        filter_fields = ()
        filters = (
            TextFilter(
                filter_id="order_status",
                label="Order status",
                field="status",
                operators=(FilterOperator.EQ,),
            ),
        )
        sort_fields = ("id",)

    admin = Admin(title="Query configuration", debug=True)
    admin.install(SQLAlchemyPlugin(session_factory=factory))
    admin.register(OrdersAdmin)
    app = admin.asgi()

    assert app is not None
    assert admin.compiled is not None
    assert admin.compiled.resources[0].field_policy.filter_fields == ()
    await engine.dispose()


async def test_sqlalchemy_page_metadata_remains_compatible(
    datasource: SQLAlchemyDataSource,
) -> None:
    result = await datasource.list(
        ResourceQuery(
            pagination=PagePagination(page=2, per_page=2),
            count_policy=CountPolicy.EXACT,
        )
    )
    assert isinstance(result, PageResult)
    assert [item.id for item in result.items] == [3, 4]
    assert result.page == 2
    assert result.per_page == 2
    assert result.has_previous is True
    assert result.has_next is False
    assert result.total_count == 4


async def test_sqlalchemy_limit_offset_exact_metadata(datasource: SQLAlchemyDataSource) -> None:
    result = await datasource.list(
        ResourceQuery(
            pagination=LimitOffsetPagination(offset=1, limit=2),
            count_policy=CountPolicy.EXACT,
        )
    )
    assert isinstance(result, LimitOffsetResult)
    assert [item.id for item in result.items] == [2, 3]
    assert result.offset == 1
    assert result.limit == 2
    assert result.has_previous is True
    assert result.has_next is True
    assert result.total_count == 4


@pytest.mark.parametrize("count_policy", (CountPolicy.DEFERRED, CountPolicy.DISABLED))
async def test_sqlalchemy_limit_offset_non_exact_uses_limit_plus_one(
    datasource: SQLAlchemyDataSource,
    count_policy: CountPolicy,
) -> None:
    result = await datasource.list(
        ResourceQuery(
            pagination=LimitOffsetPagination(offset=2, limit=1),
            count_policy=count_policy,
        )
    )
    assert isinstance(result, LimitOffsetResult)
    assert [item.id for item in result.items] == [3]
    assert result.has_previous is True
    assert result.has_next is True
    assert result.total_count is None


async def test_sqlalchemy_rejects_cursor_instead_of_emulating_it(
    datasource: SQLAlchemyDataSource,
) -> None:
    with pytest.raises(RakitError) as captured:
        await datasource.list(ResourceQuery(pagination=CursorPagination(cursor="opaque", limit=2)))

    assert captured.value.code is ErrorCode.CONFIG_INVALID_RESOURCE_POLICY
    assert captured.value.details == {"reason": "pagination_strategy_not_supported"}


async def test_sqlalchemy_still_rejects_undeclared_query_field(
    datasource: SQLAlchemyDataSource,
) -> None:
    query = ResourceQuery(
        filters=(Filter(field="secret", operator=FilterOperator.EQ, value="hidden"),)
    )
    with pytest.raises(RakitError) as captured:
        await datasource.list(query)
    assert captured.value.status_code == 400
