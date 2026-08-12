from collections.abc import AsyncIterator
from typing import cast

import pytest
from rakit_core.errors import ErrorCode, RakitError
from rakit_core.events import EventBus, EventPublisher
from rakit_core.fields import FieldDefinition
from rakit_core.forms import FormSchema
from rakit_core.mutations import MutationHooks
from rakit_sqlalchemy.mutations import ResourceCreated, SQLAlchemyMutationService
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "mutation_users"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str]
    password_hash: Mapped[str | None] = mapped_column(nullable=True)


@pytest.fixture
async def session_factory() -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    yield async_sessionmaker(engine, expire_on_commit=False)
    await engine.dispose()


@pytest.fixture
def received_events() -> tuple[EventPublisher, list[object]]:
    received: list[object] = []
    bus = EventBus()
    bus.subscribe(ResourceCreated, received.append)
    return EventPublisher(bus), received


@pytest.mark.anyio
async def test_create_commits_only_whitelisted_values_and_emits_event(
    session_factory: async_sessionmaker[AsyncSession],
    received_events: tuple[EventPublisher, list[object]],
) -> None:
    publisher, received = received_events
    service = SQLAlchemyMutationService(
        model=User,
        session_factory=session_factory,
        form_schema=FormSchema(
            fields=(FieldDefinition(field_id="name", python_type=str, required=True),)
        ),
        writable_fields=("name",),
        identity_fields=("id",),
        event_publisher=publisher,
    )

    result = await service.create({"name": "Ada"})

    assert result.identity.values == {"id": 1}
    assert cast(User, result.record).name == "Ada"
    assert [type(event).__name__ for event in received] == ["ResourceCreated"]


@pytest.mark.anyio
async def test_invalid_create_does_not_execute_or_mass_assign(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    service = SQLAlchemyMutationService(
        model=User,
        session_factory=session_factory,
        form_schema=FormSchema(
            fields=(FieldDefinition(field_id="name", python_type=str, required=True),)
        ),
        writable_fields=("name",),
        identity_fields=("id",),
    )

    with pytest.raises(RakitError) as caught:
        await service.create({"name": "Ada", "password_hash": "forged"})
    assert caught.value.code == ErrorCode.VALIDATION_FAILED


@pytest.mark.anyio
async def test_mutation_hooks_run_in_commit_order_and_pre_commit_failure_rolls_back(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    order: list[str] = []

    async def before_execute(_plan: object) -> None:
        order.append("before_execute")

    async def before_commit(_plan: object) -> None:
        order.append("before_commit")

    async def after_commit(_result: object) -> None:
        order.append("after_commit")

    service = SQLAlchemyMutationService(
        model=User,
        session_factory=session_factory,
        form_schema=FormSchema(
            fields=(FieldDefinition(field_id="name", python_type=str, required=True),)
        ),
        writable_fields=("name",),
        identity_fields=("id",),
        hooks=MutationHooks(
            before_execute=(before_execute,),
            before_commit=(before_commit,),
            after_commit=(after_commit,),
        ),
    )

    await service.create({"name": "Ada"})
    assert order == ["before_execute", "before_commit", "after_commit"]

    async def reject(_plan: object) -> None:
        raise RuntimeError("stop before commit")

    blocked = SQLAlchemyMutationService(
        model=User,
        session_factory=session_factory,
        form_schema=FormSchema(
            fields=(FieldDefinition(field_id="name", python_type=str, required=True),)
        ),
        writable_fields=("name",),
        identity_fields=("id",),
        hooks=MutationHooks(before_commit=(reject,)),
    )
    with pytest.raises(RuntimeError, match="stop before commit"):
        await blocked.create({"name": "Grace"})

    async with session_factory() as session:
        names = list((await session.scalars(select(User.name))).all())
    assert names == ["Ada"]
