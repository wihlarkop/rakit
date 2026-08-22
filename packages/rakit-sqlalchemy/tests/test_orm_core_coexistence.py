from __future__ import annotations

import asyncio

from rakit_core.compiler import ApplicationBuilder
from rakit_core.definitions import ResourceFieldPolicy
from rakit_sqlalchemy.core_plugin import SQLAlchemyCorePlugin
from rakit_sqlalchemy.plugin import SQLAlchemyPlugin
from sqlalchemy import Column, Integer, MetaData, String, Table
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Item(Base):
    __tablename__ = "orm_core_coexistence_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100))


core_metadata = MetaData()
core_items = Table(
    "orm_core_coexistence_core_items",
    core_metadata,
    Column("id", Integer, primary_key=True),
    Column("name", String(100), nullable=False),
)

POLICY = ResourceFieldPolicy(
    list_fields=("id", "name"),
    detail_fields=("id", "name"),
)


def test_sqlalchemy_orm_and_core_claimers_are_disjoint_and_can_coexist() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    try:
        session_factory = async_sessionmaker(engine, expire_on_commit=False)
        orm_plugin = SQLAlchemyPlugin(session_factory=session_factory)
        core_plugin = SQLAlchemyCorePlugin(engine=engine)
        builder = ApplicationBuilder()
        builder.install(orm_plugin)
        builder.install(core_plugin)

        orm_runtime = orm_plugin._claim(Item, POLICY)
        core_runtime = core_plugin._claim(core_items, POLICY)

        assert orm_runtime is not None
        assert core_runtime is not None
        assert orm_plugin._claim(core_items, POLICY) is None
        assert core_plugin._claim(Item, POLICY) is None
        assert tuple(provider.provider_id for provider in builder.capability_providers) == (
            "persistence.sqlalchemy",
            "persistence.sqlalchemy-core",
        )
        assert tuple(item.integration_id for item in builder.configured_integrations) == (
            "persistence.sqlalchemy",
            "persistence.sqlalchemy-core",
        )
    finally:
        asyncio.run(engine.dispose())
