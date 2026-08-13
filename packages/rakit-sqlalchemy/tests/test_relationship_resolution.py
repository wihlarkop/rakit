from collections.abc import AsyncIterator

import pytest
from rakit_core.definitions import ResourceFieldPolicy
from rakit_core.identity import RecordIdentity
from rakit_core.relationship_mutations import RelationshipCandidate
from rakit_sqlalchemy.datasource import SQLAlchemyDataSource
from rakit_sqlalchemy.relationship_mutations import SQLAlchemyRelationshipResolver
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Customer(Base):
    __tablename__ = "relationship_resolution_customers"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str]
    visible: Mapped[bool]


class VisibleCustomerDataSource(SQLAlchemyDataSource):
    def _base_statement(self):
        return select(Customer).where(Customer.visible.is_(True))


@pytest.fixture
async def session_factory() -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    yield async_sessionmaker(engine, expire_on_commit=False)
    await engine.dispose()


@pytest.mark.anyio
async def test_relationship_resolver_uses_target_scoped_query_and_returns_safe_candidate(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    source = VisibleCustomerDataSource(
        model=Customer,
        session_factory=session_factory,
        field_policy=ResourceFieldPolicy(list_fields=("id", "name"), detail_fields=("id", "name")),
    )
    async with session_factory() as session:
        session.add_all(
            (
                Customer(name="Ada", visible=True),
                Customer(name="Hidden", visible=False),
            )
        )
        await session.commit()

    resolver = SQLAlchemyRelationshipResolver(source)
    async with session_factory() as session:
        visible = await resolver.resolve(session, RecordIdentity(values={"id": 1}))
        hidden = await resolver.resolve(session, RecordIdentity(values={"id": 2}))
        candidate = await resolver.candidate(
            session, RecordIdentity(values={"id": 1}), label=lambda record: record.name
        )

    assert visible is not None
    assert hidden is None
    assert candidate == RelationshipCandidate(
        identity=RecordIdentity(values={"id": 1}), label="Ada"
    )
