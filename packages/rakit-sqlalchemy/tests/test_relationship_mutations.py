from collections.abc import AsyncIterator

import pytest
from rakit_core.auth import Principal
from rakit_core.concurrency import AttributeVersionProvider
from rakit_core.config import SecretValue
from rakit_core.crypto import TokenService
from rakit_core.definitions import ResourceFieldPolicy
from rakit_core.events import EventBus, EventPublisher
from rakit_core.idempotency import IdempotencyReservation, IdempotencyStatus, OperationReceipt
from rakit_core.identity import RecordIdentity
from rakit_core.mutations import OperationAuthorization
from rakit_core.operations import CancellationContext, OperationContext, activate_operation_context
from rakit_core.permissions import PermissionRequirement
from rakit_core.relationship_mutations import (
    RelationshipChanged,
    RelationshipMutationKind,
    RelationshipMutationPlan,
)
from rakit_core.relationships import (
    CompiledRelationship,
    RelationshipCardinality,
    RelationshipDefinition,
    RelationshipEditMode,
    RelationshipKind,
)
from rakit_sqlalchemy.datasource import SQLAlchemyDataSource
from rakit_sqlalchemy.relationship_mutations import SQLAlchemyRelationshipMutationService
from sqlalchemy import Column, ForeignKey, Table, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


order_tag = Table(
    "relationship_mutation_order_tag",
    Base.metadata,
    Column("order_id", ForeignKey("relationship_mutation_orders.id"), primary_key=True),
    Column("tag_id", ForeignKey("relationship_mutation_tags.id"), primary_key=True),
)


class Customer(Base):
    __tablename__ = "relationship_mutation_customers"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str]


class Tag(Base):
    __tablename__ = "relationship_mutation_tags"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str]


class Order(Base):
    __tablename__ = "relationship_mutation_orders"

    id: Mapped[int] = mapped_column(primary_key=True)
    version: Mapped[int] = mapped_column(default=1)
    customer_id: Mapped[int | None] = mapped_column(
        ForeignKey("relationship_mutation_customers.id")
    )
    customer: Mapped[Customer | None] = relationship()
    tags: Mapped[list[Tag]] = relationship(secondary=order_tag)


class MemoryIdempotencyStore:
    def __init__(self) -> None:
        self.claims: dict[str, tuple[str, OperationReceipt | None]] = {}

    async def begin(self, token_hash: str, *, fingerprint: str) -> IdempotencyReservation:
        existing = self.claims.get(token_hash)
        if existing is None:
            self.claims[token_hash] = (fingerprint, None)
            return IdempotencyReservation(1, IdempotencyStatus.IN_PROGRESS)
        existing_fingerprint, receipt = existing
        if existing_fingerprint != fingerprint:
            raise ValueError("fingerprint mismatch")
        return IdempotencyReservation(
            1,
            IdempotencyStatus.COMPLETED if receipt is not None else IdempotencyStatus.IN_PROGRESS,
            completed_receipt=receipt,
            claimed=False,
        )

    async def complete(
        self, reservation: IdempotencyReservation, receipt: OperationReceipt
    ) -> None:
        fingerprint, _ = self.claims[next(iter(self.claims))]
        self.claims[next(iter(self.claims))] = (fingerprint, receipt)

    async def release(self, reservation: IdempotencyReservation) -> None:
        return None

    async def fail_final(self, reservation: IdempotencyReservation) -> None:
        return None


def _identity(value: int) -> RecordIdentity:
    return RecordIdentity(values={"id": value})


def _source(model: type[object], factory: async_sessionmaker[AsyncSession]) -> SQLAlchemyDataSource:
    return SQLAlchemyDataSource(
        model=model,
        session_factory=factory,
        field_policy=ResourceFieldPolicy(list_fields=("id",), detail_fields=("id",)),
    )


def _compiled(relationship_id: str, kind: RelationshipKind) -> CompiledRelationship:
    definition = RelationshipDefinition(
        relationship_id=relationship_id,
        target_resource_id="customers" if relationship_id == "customer" else "tags",
        label=relationship_id.title(),
        kind=kind,
        cardinality=(
            RelationshipCardinality.TO_ONE
            if relationship_id == "customer"
            else RelationshipCardinality.TO_MANY
        ),
        nullable=True,
        edit_mode=RelationshipEditMode.LINK,
        writable=True,
    )
    requirement = PermissionRequirement.all_of("admin.resources.orders.update")
    return CompiledRelationship(
        source_resource_id="orders",
        definition=definition,
        mutation_permission=requirement,
        target_delete_permission=None,
        route_path=f"/orders/{{identity}}/_relationships/{relationship_id}",
    )


@pytest.fixture
async def session_factory() -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    yield async_sessionmaker(engine, expire_on_commit=False)
    await engine.dispose()


@pytest.mark.anyio
async def test_to_one_mutation_uses_scoped_records_authorization_one_uow_and_idempotency(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        session.add_all((Order(), Customer(name="Ada"), Customer(name="Grace")))
        await session.commit()

    received: list[RelationshipChanged] = []
    bus = EventBus()
    bus.subscribe(RelationshipChanged, received.append)
    requirement = PermissionRequirement.all_of("admin.resources.orders.update")
    service = SQLAlchemyRelationshipMutationService(
        session_factory=session_factory,
        parent_data_source=_source(Order, session_factory),
        relationships=(_compiled("customer", RelationshipKind.MANY_TO_ONE),),
        target_data_sources={"customers": _source(Customer, session_factory)},
        token_service=TokenService.single_key(
            key_id="test", value=SecretValue("x" * 32), admin_id="admin"
        ),
        concurrency_provider=AttributeVersionProvider("version"),
        idempotency_store=MemoryIdempotencyStore(),
    )
    token = await service.issue_concurrency_token(_identity(1), "customer")
    plan = RelationshipMutationPlan(
        operation_id="relationship:orders:customer:set",
        parent_resource_id="orders",
        parent_identity=_identity(1),
        relationship_id="customer",
        kind=RelationshipMutationKind.SET,
        target_identities=(_identity(1),),
        authorization_requirement=requirement,
        concurrency_token=token,
        idempotency_token="submission-1",
    )
    authorization = OperationAuthorization.for_requirement(
        admin_id="admin",
        resource_id="orders",
        operation=plan.operation_id,
        principal_id="operator",
        requirement=requirement,
        target_identity=plan.parent_identity,
    )
    context = OperationContext(
        deadline=None,
        cancellation=CancellationContext(),
        principal=Principal(subject_id="operator", authenticated=True),
        admin_id="admin",
        resource_id="orders",
        operation=plan.operation_id,
        permission_requirement=requirement,
        events=EventPublisher(bus),
    )

    with activate_operation_context(context):
        result = await service.execute(plan, authorization=authorization)

    assert result.target_identities == (_identity(1),)
    assert result.added_target_identities == (_identity(1),)
    assert len(received) == 1
    async with session_factory() as session:
        order = (await session.scalars(select(Order))).one()
        assert order.customer_id == 1


@pytest.mark.anyio
async def test_secondary_many_to_many_replace_is_atomic_and_unlinks_without_deleting_targets(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        session.add_all((Order(), Tag(name="first"), Tag(name="second")))
        await session.commit()
        order = (await session.scalars(select(Order))).one()
        first = (await session.scalars(select(Tag).where(Tag.name == "first"))).one()
        await session.refresh(order, attribute_names=["tags"])
        order.tags.append(first)
        await session.commit()

    requirement = PermissionRequirement.all_of("admin.resources.orders.update")
    service = SQLAlchemyRelationshipMutationService(
        session_factory=session_factory,
        parent_data_source=_source(Order, session_factory),
        relationships=(_compiled("tags", RelationshipKind.MANY_TO_MANY),),
        target_data_sources={"tags": _source(Tag, session_factory)},
        token_service=TokenService.single_key(
            key_id="test", value=SecretValue("x" * 32), admin_id="admin"
        ),
        concurrency_provider=AttributeVersionProvider("version"),
        idempotency_store=MemoryIdempotencyStore(),
    )
    token = await service.issue_concurrency_token(_identity(1), "tags")
    plan = RelationshipMutationPlan(
        operation_id="relationship:orders:tags:replace",
        parent_resource_id="orders",
        parent_identity=_identity(1),
        relationship_id="tags",
        kind=RelationshipMutationKind.REPLACE,
        target_identities=(_identity(2),),
        authorization_requirement=requirement,
        concurrency_token=token,
        idempotency_token="submission-tags",
    )
    authorization = OperationAuthorization.for_requirement(
        admin_id="admin",
        resource_id="orders",
        operation=plan.operation_id,
        principal_id="operator",
        requirement=requirement,
        target_identity=plan.parent_identity,
    )
    context = OperationContext(
        deadline=None,
        cancellation=CancellationContext(),
        principal=Principal(subject_id="operator", authenticated=True),
        admin_id="admin",
        resource_id="orders",
        operation=plan.operation_id,
        permission_requirement=requirement,
    )

    with activate_operation_context(context):
        result = await service.execute(plan, authorization=authorization)

    assert result.target_identities == (_identity(2),)
    assert result.added_target_identities == (_identity(2),)
    assert result.removed_target_identities == (_identity(1),)
    async with session_factory() as session:
        order = (await session.scalars(select(Order))).one()
        await session.refresh(order, attribute_names=["tags"])
        assert [tag.name for tag in order.tags] == ["second"]
        assert list((await session.scalars(select(Tag.name).order_by(Tag.id))).all()) == [
            "first",
            "second",
        ]
