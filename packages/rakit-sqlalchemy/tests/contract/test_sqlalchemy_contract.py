"""The SQLAlchemy adapter must pass the reusable DataSource contract suite.

This is the official proof that ``rakit-sqlalchemy`` honors the backend-neutral
read contract: list/detail/not-found, identity, filtering, search,
deterministic sorting, identity tie-breakers, pagination, count policy
semantics, and portable error translation.

The adapter is read-only (``DataSourceCapabilities(read=True)``), so the
capability-gated write/transaction/concurrency branches are correctly skipped.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Mapping

import pytest
from rakit_core.definitions import ResourceFieldPolicy
from rakit_core.testing import DataSourceContractSuite
from rakit_sqlalchemy.datasource import SQLAlchemyDataSource
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class ContractUser(Base):
    __tablename__ = "contract_users"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str]
    name: Mapped[str]
    group: Mapped[str]
    score: Mapped[int]


FIXTURE = (
    {
        "id": 1,
        "email": "ada@example.com",
        "name": "Ada Lovelace",
        "group": "engineering",
        "score": 10,
    },
    {
        "id": 2,
        "email": "grace@example.com",
        "name": "Grace Hopper",
        "group": "engineering",
        "score": 20,
    },
    {"id": 3, "email": "alan@example.com", "name": "Alan Turing", "group": "science", "score": 30},
    {
        "id": 4,
        "email": "linus@example.com",
        "name": "Linus Torvalds",
        "group": "science",
        "score": 40,
    },
    {
        "id": 5,
        "email": "mary@example.com",
        "name": "Mary Jackson",
        "group": "operations",
        "score": 50,
    },
    {
        "id": 6,
        "email": "katherine@example.com",
        "name": "Katherine Johnson",
        "group": "engineering",
        "score": 60,
    },
    {
        "id": 7,
        "email": "dorothy@example.com",
        "name": "Dorothy Vaughan",
        "group": "operations",
        "score": 70,
    },
)


class SQLAlchemyDataSourceContract(DataSourceContractSuite):
    field_policy = ResourceFieldPolicy(
        list_fields=("id", "email", "name", "group", "score"),
        detail_fields=("id", "email", "name", "group", "score"),
        filter_fields=("email", "group", "score"),
        search_fields=("email", "name"),
        sort_fields=("email", "name", "group", "score"),
    )
    identity_fields = ("id",)
    sort_group_field = "group"

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def make_datasource(self) -> SQLAlchemyDataSource:
        return SQLAlchemyDataSource(
            model=ContractUser,
            session_factory=self._session_factory,
            field_policy=self.field_policy,
        )

    async def fixture_records(self) -> tuple[Mapping[str, object], ...]:
        return tuple(FIXTURE)


@pytest.fixture
async def session_factory() -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        session.add_all(ContractUser(**record) for record in FIXTURE)
        await session.commit()

    yield factory

    await engine.dispose()


@pytest.mark.anyio
async def test_sqlalchemy_adapter_passes_datasource_contract(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    suite = SQLAlchemyDataSourceContract(session_factory)
    await suite.run_all()
    assert suite.skipped == (
        "assert_transactions",
        "assert_writes",
        "assert_concurrency",
        "assert_cancellation_declarations",
    ), "the read-only adapter must skip exactly the write-capability branches"
