from collections.abc import AsyncIterator
from datetime import timedelta
from uuid import UUID, uuid4

import anyio
import pytest
from rakit_auth_sqlalchemy.idempotency import SQLAlchemyIdempotencyStore
from rakit_auth_sqlalchemy.models import IdempotencyRecord
from rakit_core.auth import Principal
from rakit_core.concurrency import AttributeVersionProvider
from rakit_core.config import SecretValue
from rakit_core.crypto import TokenService
from rakit_core.definitions import ResourceFieldPolicy
from rakit_core.errors import RakitError
from rakit_core.events import EventBus, EventPublisher
from rakit_core.idempotency import IdempotencyReservation, IdempotencyStatus, OperationReceipt
from rakit_core.identity import RecordIdentity
from rakit_core.mutations import OperationAuthorization
from rakit_core.operations import CancellationContext, OperationContext, activate_operation_context
from rakit_core.permissions import PermissionRequirement
from rakit_core.relationship_mutations import (
    AssociationScalarChange,
    RelationshipChanged,
    RelationshipMutationKind,
    RelationshipMutationPlan,
)
from rakit_core.relationships import (
    CompiledRelationship,
    RelationshipCardinality,
    RelationshipDefinition,
    RelationshipDestructivePolicy,
    RelationshipEditMode,
    RelationshipKind,
)
from rakit_core.transactions import TransactionPolicy
from rakit_sqlalchemy.datasource import SQLAlchemyDataSource
from rakit_sqlalchemy.relationship_mutations import SQLAlchemyRelationshipMutationService
from rakit_sqlalchemy.uow import SQLAlchemyUnitOfWork
from sqlalchemy import Column, ForeignKey, Table, Uuid, select
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
    items: Mapped[list["Item"]] = relationship(back_populates="order")
    tags: Mapped[list[Tag]] = relationship(secondary=order_tag)


class Item(Base):
    __tablename__ = "relationship_mutation_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str]
    order_id: Mapped[int | None] = mapped_column(
        ForeignKey("relationship_mutation_orders.id"), nullable=True
    )
    order: Mapped[Order | None] = relationship(back_populates="items")


class Student(Base):
    __tablename__ = "relationship_mutation_students"

    id: Mapped[int] = mapped_column(primary_key=True)
    version: Mapped[int] = mapped_column(default=1)
    enrollments: Mapped[list["Enrollment"]] = relationship(back_populates="student")


class Course(Base):
    __tablename__ = "relationship_mutation_courses"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str]
    enrollments: Mapped[list["Enrollment"]] = relationship(back_populates="course")


class Enrollment(Base):
    __tablename__ = "relationship_mutation_enrollments"

    id: Mapped[int] = mapped_column(primary_key=True)
    student_id: Mapped[int] = mapped_column(ForeignKey("relationship_mutation_students.id"))
    course_id: Mapped[int] = mapped_column(ForeignKey("relationship_mutation_courses.id"))
    grade: Mapped[str]
    student: Mapped[Student] = relationship(back_populates="enrollments")
    course: Mapped[Course] = relationship(back_populates="enrollments")


class DeleteParent(Base):
    __tablename__ = "relationship_mutation_delete_parents"

    id: Mapped[int] = mapped_column(primary_key=True)
    version: Mapped[int] = mapped_column(default=1)
    children: Mapped[list["DeleteChild"]] = relationship(
        back_populates="parent", cascade="all, delete-orphan"
    )


class DeleteChild(Base):
    __tablename__ = "relationship_mutation_delete_children"

    id: Mapped[int] = mapped_column(primary_key=True)
    parent_id: Mapped[int] = mapped_column(ForeignKey("relationship_mutation_delete_parents.id"))
    name: Mapped[str]
    parent: Mapped[DeleteParent] = relationship(back_populates="children")


class DeleteCascadeParent(Base):
    __tablename__ = "relationship_mutation_delete_cascade_parents"

    id: Mapped[int] = mapped_column(primary_key=True)
    version: Mapped[int] = mapped_column(default=1)
    children: Mapped[list["DeleteCascadeChild"]] = relationship(
        back_populates="parent", cascade="all, delete"
    )


class DeleteCascadeChild(Base):
    __tablename__ = "relationship_mutation_delete_cascade_children"

    id: Mapped[int] = mapped_column(primary_key=True)
    parent_id: Mapped[int | None] = mapped_column(
        ForeignKey("relationship_mutation_delete_cascade_parents.id"), nullable=True
    )
    name: Mapped[str]
    parent: Mapped[DeleteCascadeParent | None] = relationship(back_populates="children")


class UUIDCustomer(Base):
    __tablename__ = "relationship_mutation_uuid_customers"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    name: Mapped[str]


class UUIDOrder(Base):
    __tablename__ = "relationship_mutation_uuid_orders"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    version: Mapped[int] = mapped_column(default=1)
    customer_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("relationship_mutation_uuid_customers.id")
    )
    customer: Mapped[UUIDCustomer | None] = relationship()


class VisibleOrderDataSource(SQLAlchemyDataSource):
    def _base_statement(self):
        return select(Order).where(Order.id == 1)


class VisibleCustomerDataSource(SQLAlchemyDataSource):
    def _base_statement(self):
        return select(Customer).where(Customer.id == 1)


class MemoryIdempotencyStore:
    def __init__(self) -> None:
        self.claims: dict[str, tuple[str, OperationReceipt | None]] = {}
        self._reservation_tokens: dict[int, str] = {}
        self._next_reservation_id = 1

    async def begin(self, token_hash: str, *, fingerprint: str) -> IdempotencyReservation:
        existing = self.claims.get(token_hash)
        if existing is None:
            self.claims[token_hash] = (fingerprint, None)
            reservation_id = self._next_reservation_id
            self._next_reservation_id += 1
            self._reservation_tokens[reservation_id] = token_hash
            return IdempotencyReservation(reservation_id, IdempotencyStatus.IN_PROGRESS)
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
        token_hash = self._reservation_tokens[reservation.reservation_id]
        fingerprint, _ = self.claims[token_hash]
        self.claims[token_hash] = (fingerprint, receipt)

    async def release(self, reservation: IdempotencyReservation) -> None:
        token_hash = self._reservation_tokens.get(reservation.reservation_id)
        if token_hash is not None:
            self.claims.pop(token_hash, None)

    async def fail_final(self, reservation: IdempotencyReservation) -> None:
        return None


def _identity(value: int) -> RecordIdentity:
    return RecordIdentity(values={"id": value})


def _uuid_identity(value: UUID) -> RecordIdentity:
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
        target_resource_id={"customer": "customers", "items": "items"}.get(relationship_id, "tags"),
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


@pytest.mark.anyio
async def test_one_to_many_add_and_remove_use_one_atomic_collection_mutation(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        session.add_all((Order(), Item(name="first"), Item(name="second")))
        await session.commit()

    requirement = PermissionRequirement.all_of("admin.resources.orders.update")
    service = SQLAlchemyRelationshipMutationService(
        session_factory=session_factory,
        parent_data_source=_source(Order, session_factory),
        relationships=(_compiled("items", RelationshipKind.ONE_TO_MANY),),
        target_data_sources={"items": _source(Item, session_factory)},
        token_service=TokenService.single_key(
            key_id="test", value=SecretValue("x" * 32), admin_id="admin"
        ),
        concurrency_provider=AttributeVersionProvider("version"),
        idempotency_store=MemoryIdempotencyStore(),
    )
    token = await service.issue_concurrency_token(_identity(1), "items")
    plan = RelationshipMutationPlan(
        operation_id="relationship:orders:items:add",
        parent_resource_id="orders",
        parent_identity=_identity(1),
        relationship_id="items",
        kind=RelationshipMutationKind.ADD,
        target_identities=(_identity(1), _identity(2)),
        authorization_requirement=requirement,
        concurrency_token=token,
        idempotency_token="submission-items",
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

    assert result.target_identities == (_identity(1), _identity(2))
    async with session_factory() as session:
        assert list((await session.scalars(select(Item.order_id).order_by(Item.id))).all()) == [
            1,
            1,
        ]


@pytest.mark.anyio
async def test_association_object_adds_only_declared_scalars_and_never_mass_assigns_identity_or_fks(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        session.add_all((Student(), Course(name="Math")))
        await session.commit()

    requirement = PermissionRequirement.all_of("admin.resources.students.update")
    definition = RelationshipDefinition(
        relationship_id="enrollments",
        target_resource_id="enrollments",
        association_target_resource_id="courses",
        label="Courses",
        kind=RelationshipKind.ASSOCIATION_OBJECT,
        cardinality=RelationshipCardinality.TO_MANY,
        edit_mode=RelationshipEditMode.LINK,
        writable=True,
        association_fields=("grade",),
    )
    compiled = CompiledRelationship(
        source_resource_id="students",
        definition=definition,
        mutation_permission=requirement,
        target_delete_permission=None,
        route_path="/students/{identity}/_relationships/enrollments",
    )
    service = SQLAlchemyRelationshipMutationService(
        session_factory=session_factory,
        parent_data_source=_source(Student, session_factory),
        relationships=(compiled,),
        target_data_sources={
            "enrollments": _source(Enrollment, session_factory),
            "courses": _source(Course, session_factory),
        },
        token_service=TokenService.single_key(
            key_id="test", value=SecretValue("x" * 32), admin_id="admin"
        ),
        concurrency_provider=AttributeVersionProvider("version"),
        idempotency_store=MemoryIdempotencyStore(),
    )
    token = await service.issue_concurrency_token(_identity(1), "enrollments")
    plan = RelationshipMutationPlan(
        operation_id="relationship:students:enrollments:add",
        parent_resource_id="students",
        parent_identity=_identity(1),
        relationship_id="enrollments",
        kind=RelationshipMutationKind.ADD,
        target_identities=(_identity(1),),
        association_changes=(
            AssociationScalarChange(target_identity=_identity(1), values={"grade": "A"}),
        ),
        authorization_requirement=requirement,
        concurrency_token=token,
        idempotency_token="submission-enrollment",
    )
    authorization = OperationAuthorization.for_requirement(
        admin_id="admin",
        resource_id="students",
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
        resource_id="students",
        operation=plan.operation_id,
        permission_requirement=requirement,
    )
    with activate_operation_context(context):
        result = await service.execute(plan, authorization=authorization)

    assert result.target_identities == (_identity(1),)
    async with session_factory() as session:
        enrollment = (await session.scalars(select(Enrollment))).one()
        assert (enrollment.id, enrollment.student_id, enrollment.course_id, enrollment.grade) == (
            1,
            1,
            1,
            "A",
        )


@pytest.mark.anyio
async def test_delete_orphan_relationship_change_is_rejected_before_mutation_without_policy(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        parent = DeleteParent()
        parent.children.append(DeleteChild(name="child"))
        session.add(parent)
        await session.commit()

    requirement = PermissionRequirement.all_of("admin.resources.parents.update")
    definition = RelationshipDefinition(
        relationship_id="children",
        target_resource_id="children",
        label="Children",
        kind=RelationshipKind.ONE_TO_MANY,
        cardinality=RelationshipCardinality.TO_MANY,
        edit_mode=RelationshipEditMode.LINK,
        writable=True,
        destructive_policy=RelationshipDestructivePolicy(),
    )
    compiled = CompiledRelationship(
        source_resource_id="parents",
        definition=definition,
        mutation_permission=requirement,
        target_delete_permission=None,
        route_path="/parents/{identity}/_relationships/children",
    )
    service = SQLAlchemyRelationshipMutationService(
        session_factory=session_factory,
        parent_data_source=_source(DeleteParent, session_factory),
        relationships=(compiled,),
        target_data_sources={"children": _source(DeleteChild, session_factory)},
        token_service=TokenService.single_key(
            key_id="test", value=SecretValue("x" * 32), admin_id="admin"
        ),
        concurrency_provider=AttributeVersionProvider("version"),
        idempotency_store=MemoryIdempotencyStore(),
    )
    token = await service.issue_concurrency_token(_identity(1), "children")
    plan = RelationshipMutationPlan(
        operation_id="relationship:parents:children:replace",
        parent_resource_id="parents",
        parent_identity=_identity(1),
        relationship_id="children",
        kind=RelationshipMutationKind.REPLACE,
        authorization_requirement=requirement,
        concurrency_token=token,
        idempotency_token="submission-delete-orphan",
    )
    authorization = OperationAuthorization.for_requirement(
        admin_id="admin",
        resource_id="parents",
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
        resource_id="parents",
        operation=plan.operation_id,
        permission_requirement=requirement,
    )
    with activate_operation_context(context), pytest.raises(RakitError) as caught:
        await service.execute(plan, authorization=authorization)

    assert caught.value.code == "validation.failed"
    async with session_factory() as session:
        assert list((await session.scalars(select(DeleteChild.name))).all()) == ["child"]


@pytest.mark.anyio
async def test_successful_relationship_change_makes_the_old_snapshot_stale(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        session.add_all((Order(), Customer(name="Ada"), Customer(name="Grace")))
        await session.commit()

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
    stale_token = await service.issue_concurrency_token(_identity(1), "customer")

    def plan(target: int, submission: str) -> RelationshipMutationPlan:
        return RelationshipMutationPlan(
            operation_id="relationship:orders:customer:set",
            parent_resource_id="orders",
            parent_identity=_identity(1),
            relationship_id="customer",
            kind=RelationshipMutationKind.SET,
            target_identities=(_identity(target),),
            authorization_requirement=requirement,
            concurrency_token=stale_token,
            idempotency_token=submission,
        )

    authorization = OperationAuthorization.for_requirement(
        admin_id="admin",
        resource_id="orders",
        operation="relationship:orders:customer:set",
        principal_id="operator",
        requirement=requirement,
        target_identity=_identity(1),
    )
    context = OperationContext(
        deadline=None,
        cancellation=CancellationContext(),
        principal=Principal(subject_id="operator", authenticated=True),
        admin_id="admin",
        resource_id="orders",
        operation="relationship:orders:customer:set",
        permission_requirement=requirement,
    )
    with activate_operation_context(context):
        await service.execute(plan(1, "first"), authorization=authorization)
        with pytest.raises(RakitError) as caught:
            await service.execute(plan(2, "second"), authorization=authorization)

    assert caught.value.code == "resource.conflict"
    async with session_factory() as session:
        assert (await session.scalars(select(Order.customer_id))).one() == 1


async def _association_service(
    session_factory: async_sessionmaker[AsyncSession],
) -> tuple[
    SQLAlchemyRelationshipMutationService,
    PermissionRequirement,
    TokenService,
    MemoryIdempotencyStore,
]:
    requirement = PermissionRequirement.all_of("admin.resources.students.update")
    definition = RelationshipDefinition(
        relationship_id="enrollments",
        target_resource_id="enrollments",
        association_target_resource_id="courses",
        label="Courses",
        kind=RelationshipKind.ASSOCIATION_OBJECT,
        cardinality=RelationshipCardinality.TO_MANY,
        edit_mode=RelationshipEditMode.LINK,
        writable=True,
        association_fields=("grade",),
    )
    compiled = CompiledRelationship(
        source_resource_id="students",
        definition=definition,
        mutation_permission=requirement,
        target_delete_permission=None,
        route_path="/students/{identity}/_relationships/enrollments",
    )
    tokens = TokenService.single_key(key_id="test", value=SecretValue("x" * 32), admin_id="admin")
    store = MemoryIdempotencyStore()
    return (
        SQLAlchemyRelationshipMutationService(
            session_factory=session_factory,
            parent_data_source=_source(Student, session_factory),
            relationships=(compiled,),
            target_data_sources={
                "enrollments": _source(Enrollment, session_factory),
                "courses": _source(Course, session_factory),
            },
            token_service=tokens,
            concurrency_provider=AttributeVersionProvider("version"),
            idempotency_store=store,
        ),
        requirement,
        tokens,
        store,
    )


def _relationship_context(
    *, resource_id: str, operation: str, requirement: PermissionRequirement, session_id: str = ""
) -> OperationContext:
    return OperationContext(
        deadline=None,
        cancellation=CancellationContext(),
        principal=Principal(subject_id="operator", authenticated=True),
        admin_id="admin",
        session_id=session_id,
        resource_id=resource_id,
        operation=operation,
        permission_requirement=requirement,
    )


def _relationship_authorization(
    *,
    resource_id: str,
    operation: str,
    parent_identity: RecordIdentity,
    requirement: PermissionRequirement,
) -> OperationAuthorization:
    return OperationAuthorization.for_requirement(
        admin_id="admin",
        resource_id=resource_id,
        operation=operation,
        principal_id="operator",
        requirement=requirement,
        target_identity=parent_identity,
    )


async def _customer_service(
    session_factory: async_sessionmaker[AsyncSession],
) -> tuple[SQLAlchemyRelationshipMutationService, PermissionRequirement]:
    requirement = PermissionRequirement.all_of("admin.resources.orders.update")
    return (
        SQLAlchemyRelationshipMutationService(
            session_factory=session_factory,
            parent_data_source=_source(Order, session_factory),
            relationships=(_compiled("customer", RelationshipKind.MANY_TO_ONE),),
            target_data_sources={"customers": _source(Customer, session_factory)},
            token_service=TokenService.single_key(
                key_id="test", value=SecretValue("x" * 32), admin_id="admin"
            ),
            concurrency_provider=AttributeVersionProvider("version"),
            idempotency_store=MemoryIdempotencyStore(),
        ),
        requirement,
    )


@pytest.mark.anyio
async def test_association_object_update_changes_only_declared_scalar(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        student = Student()
        course = Course(name="Math")
        student.enrollments.append(Enrollment(course=course, grade="B"))
        session.add(student)
        await session.commit()

    service, requirement, _tokens, _store = await _association_service(session_factory)
    token = await service.issue_concurrency_token(_identity(1), "enrollments")
    operation = "relationship:students:enrollments:update"
    plan = RelationshipMutationPlan(
        operation_id=operation,
        parent_resource_id="students",
        parent_identity=_identity(1),
        relationship_id="enrollments",
        kind=RelationshipMutationKind.UPDATE,
        target_identities=(_identity(1),),
        association_changes=(
            AssociationScalarChange(
                target_identity=_identity(1),
                association_identity=_identity(1),
                values={"grade": "A"},
            ),
        ),
        authorization_requirement=requirement,
        concurrency_token=token,
        idempotency_token="association-update",
    )
    with activate_operation_context(
        _relationship_context(resource_id="students", operation=operation, requirement=requirement)
    ):
        await service.execute(
            plan,
            authorization=_relationship_authorization(
                resource_id="students",
                operation=operation,
                parent_identity=_identity(1),
                requirement=requirement,
            ),
        )

    async with session_factory() as session:
        enrollment = (await session.scalars(select(Enrollment))).one()
        assert enrollment.grade == "A"
        assert (enrollment.id, enrollment.student_id, enrollment.course_id) == (1, 1, 1)


@pytest.mark.anyio
async def test_association_object_unlink_deletes_edge_but_preserves_target(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        student = Student()
        course = Course(name="Math")
        student.enrollments.append(Enrollment(course=course, grade="B"))
        session.add(student)
        await session.commit()

    service, requirement, _tokens, _store = await _association_service(session_factory)
    token = await service.issue_concurrency_token(_identity(1), "enrollments")
    operation = "relationship:students:enrollments:remove"
    plan = RelationshipMutationPlan(
        operation_id=operation,
        parent_resource_id="students",
        parent_identity=_identity(1),
        relationship_id="enrollments",
        kind=RelationshipMutationKind.REMOVE,
        target_identities=(_identity(1),),
        authorization_requirement=requirement,
        concurrency_token=token,
        idempotency_token="association-unlink",
    )
    with activate_operation_context(
        _relationship_context(resource_id="students", operation=operation, requirement=requirement)
    ):
        result = await service.execute(
            plan,
            authorization=_relationship_authorization(
                resource_id="students",
                operation=operation,
                parent_identity=_identity(1),
                requirement=requirement,
            ),
        )

    assert result.target_identities == ()
    async with session_factory() as session:
        assert list((await session.scalars(select(Enrollment))).all()) == []
        assert list((await session.scalars(select(Course.name))).all()) == ["Math"]


@pytest.mark.anyio
async def test_association_object_replace_reconciles_add_retain_update_and_remove_atomically(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        student = Student()
        first, second, third = Course(name="First"), Course(name="Second"), Course(name="Third")
        student.enrollments.extend(
            (Enrollment(course=first, grade="B"), Enrollment(course=third, grade="C"))
        )
        session.add_all((student, second))
        await session.commit()

    service, requirement, _tokens, _store = await _association_service(session_factory)
    token = await service.issue_concurrency_token(_identity(1), "enrollments")
    operation = "relationship:students:enrollments:replace"
    plan = RelationshipMutationPlan(
        operation_id=operation,
        parent_resource_id="students",
        parent_identity=_identity(1),
        relationship_id="enrollments",
        kind=RelationshipMutationKind.REPLACE,
        target_identities=(_identity(1), _identity(2)),
        association_changes=(
            AssociationScalarChange(target_identity=_identity(1), values={"grade": "A"}),
            AssociationScalarChange(target_identity=_identity(2), values={"grade": "A+"}),
        ),
        authorization_requirement=requirement,
        concurrency_token=token,
        idempotency_token="association-replace",
    )
    with activate_operation_context(
        _relationship_context(resource_id="students", operation=operation, requirement=requirement)
    ):
        result = await service.execute(
            plan,
            authorization=_relationship_authorization(
                resource_id="students",
                operation=operation,
                parent_identity=_identity(1),
                requirement=requirement,
            ),
        )

    assert result.target_identities == (_identity(1), _identity(2))
    async with session_factory() as session:
        enrollments = list(
            (await session.scalars(select(Enrollment).order_by(Enrollment.course_id))).all()
        )
        assert [(edge.course_id, edge.grade) for edge in enrollments] == [(1, "A"), (2, "A+")]
        assert list((await session.scalars(select(Course.id).order_by(Course.id))).all()) == [
            1,
            2,
            3,
        ]


@pytest.mark.anyio
@pytest.mark.parametrize("field", ("id", "student_id", "course_id"))
async def test_association_object_replace_rejects_undeclared_scalar_without_partial_change(
    session_factory: async_sessionmaker[AsyncSession], field: str
) -> None:
    async with session_factory() as session:
        student = Student()
        first, second = Course(name="First"), Course(name="Second")
        student.enrollments.append(Enrollment(course=first, grade="B"))
        session.add_all((student, second))
        await session.commit()

    service, requirement, _tokens, _store = await _association_service(session_factory)
    token = await service.issue_concurrency_token(_identity(1), "enrollments")
    operation = "relationship:students:enrollments:replace"
    plan = RelationshipMutationPlan(
        operation_id=operation,
        parent_resource_id="students",
        parent_identity=_identity(1),
        relationship_id="enrollments",
        kind=RelationshipMutationKind.REPLACE,
        target_identities=(_identity(1), _identity(2)),
        association_changes=(
            AssociationScalarChange(target_identity=_identity(2), values={field: 7}),
        ),
        authorization_requirement=requirement,
        concurrency_token=token,
        idempotency_token="association-invalid-replace",
    )
    with (
        activate_operation_context(
            _relationship_context(
                resource_id="students", operation=operation, requirement=requirement
            )
        ),
        pytest.raises(RakitError) as caught,
    ):
        await service.execute(
            plan,
            authorization=_relationship_authorization(
                resource_id="students",
                operation=operation,
                parent_identity=_identity(1),
                requirement=requirement,
            ),
        )

    assert caught.value.code == "validation.failed"
    async with session_factory() as session:
        enrollments = list((await session.scalars(select(Enrollment))).all())
        assert [(edge.course_id, edge.grade) for edge in enrollments] == [(1, "B")]


@pytest.mark.anyio
async def test_relationship_execution_fails_closed_for_missing_or_mismatched_authorization(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        session.add_all((Order(), Customer(name="Ada"), Customer(name="Grace")))
        await session.commit()

    service, requirement = await _customer_service(session_factory)
    token = await service.issue_concurrency_token(_identity(1), "customer")
    operation = "relationship:orders:customer:set"
    plan = RelationshipMutationPlan(
        operation_id=operation,
        parent_resource_id="orders",
        parent_identity=_identity(1),
        relationship_id="customer",
        kind=RelationshipMutationKind.SET,
        target_identities=(_identity(1),),
        authorization_requirement=requirement,
        concurrency_token=token,
        idempotency_token="authorization-test",
    )
    valid_context = _relationship_context(
        resource_id="orders", operation=operation, requirement=requirement
    )
    valid = _relationship_authorization(
        resource_id="orders",
        operation=operation,
        parent_identity=_identity(1),
        requirement=requirement,
    )
    invalid_capabilities = (
        None,
        OperationAuthorization.for_requirement(
            admin_id="other-admin",
            resource_id="orders",
            operation=operation,
            principal_id="operator",
            requirement=requirement,
            target_identity=_identity(1),
        ),
        OperationAuthorization.for_requirement(
            admin_id="admin",
            resource_id="orders",
            operation=operation,
            principal_id="other-principal",
            requirement=requirement,
            target_identity=_identity(1),
        ),
        OperationAuthorization.for_requirement(
            admin_id="admin",
            resource_id="customers",
            operation=operation,
            principal_id="operator",
            requirement=requirement,
            target_identity=_identity(1),
        ),
        OperationAuthorization.for_requirement(
            admin_id="admin",
            resource_id="orders",
            operation="relationship:orders:tags:add",
            principal_id="operator",
            requirement=requirement,
            target_identity=_identity(1),
        ),
        OperationAuthorization.for_requirement(
            admin_id="admin",
            resource_id="orders",
            operation=operation,
            principal_id="operator",
            requirement=PermissionRequirement.any_of(*requirement.permissions),
            target_identity=_identity(1),
        ),
        OperationAuthorization.for_requirement(
            admin_id="admin",
            resource_id="orders",
            operation=operation,
            principal_id="operator",
            requirement=requirement,
            target_identity=_identity(2),
        ),
    )
    for capability in invalid_capabilities:
        with activate_operation_context(valid_context), pytest.raises(RakitError) as caught:
            await service.execute(plan, authorization=capability)
        assert caught.value.code == "auth.forbidden"

    with activate_operation_context(valid_context):
        result = await service.execute(plan, authorization=valid)
    assert result.target_identities == (_identity(1),)


@pytest.mark.anyio
async def test_relationship_execution_resolves_parent_and_targets_only_through_scoped_sources(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        session.add_all((Order(), Order(), Customer(name="Visible"), Customer(name="Hidden")))
        await session.commit()

    requirement = PermissionRequirement.all_of("admin.resources.orders.update")
    service = SQLAlchemyRelationshipMutationService(
        session_factory=session_factory,
        parent_data_source=VisibleOrderDataSource(
            model=Order,
            session_factory=session_factory,
            field_policy=ResourceFieldPolicy(list_fields=("id",), detail_fields=("id",)),
        ),
        relationships=(_compiled("customer", RelationshipKind.MANY_TO_ONE),),
        target_data_sources={
            "customers": VisibleCustomerDataSource(
                model=Customer,
                session_factory=session_factory,
                field_policy=ResourceFieldPolicy(list_fields=("id",), detail_fields=("id",)),
            )
        },
        token_service=TokenService.single_key(
            key_id="test", value=SecretValue("x" * 32), admin_id="admin"
        ),
        concurrency_provider=AttributeVersionProvider("version"),
        idempotency_store=MemoryIdempotencyStore(),
    )
    operation = "relationship:orders:customer:set"
    context = _relationship_context(
        resource_id="orders", operation=operation, requirement=requirement
    )

    with pytest.raises(RakitError) as hidden_parent:
        await service.issue_concurrency_token(_identity(2), "customer")
    assert hidden_parent.value.code == "resource.not_found"

    token = await service.issue_concurrency_token(_identity(1), "customer")
    hidden_target = RelationshipMutationPlan(
        operation_id=operation,
        parent_resource_id="orders",
        parent_identity=_identity(1),
        relationship_id="customer",
        kind=RelationshipMutationKind.SET,
        target_identities=(_identity(2),),
        authorization_requirement=requirement,
        concurrency_token=token,
        idempotency_token="hidden-target",
    )
    with activate_operation_context(context), pytest.raises(RakitError) as caught:
        await service.execute(
            hidden_target,
            authorization=_relationship_authorization(
                resource_id="orders",
                operation=operation,
                parent_identity=_identity(1),
                requirement=requirement,
            ),
        )
    assert caught.value.code == "resource.not_found"
    async with session_factory() as session:
        assert (await session.scalars(select(Order.customer_id).where(Order.id == 1))).one() is None


async def _destructive_service(
    session_factory: async_sessionmaker[AsyncSession],
) -> tuple[SQLAlchemyRelationshipMutationService, PermissionRequirement, PermissionRequirement]:
    relationship_requirement = PermissionRequirement.all_of("admin.resources.parents.update")
    delete_requirement = PermissionRequirement.all_of("admin.resources.children.delete")
    definition = RelationshipDefinition(
        relationship_id="children",
        target_resource_id="children",
        label="Children",
        kind=RelationshipKind.ONE_TO_MANY,
        cardinality=RelationshipCardinality.TO_MANY,
        edit_mode=RelationshipEditMode.LINK,
        writable=True,
        destructive_policy=RelationshipDestructivePolicy(
            allow_delete_orphan=True, allow_destructive_cascade=True
        ),
    )
    compiled = CompiledRelationship(
        source_resource_id="parents",
        definition=definition,
        mutation_permission=relationship_requirement,
        target_delete_permission=delete_requirement,
        route_path="/parents/{identity}/_relationships/children",
    )
    return (
        SQLAlchemyRelationshipMutationService(
            session_factory=session_factory,
            parent_data_source=_source(DeleteParent, session_factory),
            relationships=(compiled,),
            target_data_sources={"children": _source(DeleteChild, session_factory)},
            token_service=TokenService.single_key(
                key_id="test", value=SecretValue("x" * 32), admin_id="admin"
            ),
            concurrency_provider=AttributeVersionProvider("version"),
            idempotency_store=MemoryIdempotencyStore(),
        ),
        relationship_requirement,
        delete_requirement,
    )


async def _destructive_plan(
    service: SQLAlchemyRelationshipMutationService,
    requirement: PermissionRequirement,
    *,
    submission: str,
) -> RelationshipMutationPlan:
    operation = "relationship:parents:children:remove"
    return RelationshipMutationPlan(
        operation_id=operation,
        parent_resource_id="parents",
        parent_identity=_identity(1),
        relationship_id="children",
        kind=RelationshipMutationKind.REMOVE,
        target_identities=(_identity(1),),
        authorization_requirement=requirement,
        concurrency_token=await service.issue_concurrency_token(_identity(1), "children"),
        idempotency_token=submission,
    )


def _destructive_context(operation: str, requirement: PermissionRequirement) -> OperationContext:
    return _relationship_context(
        resource_id="parents", operation=operation, requirement=requirement
    )


def _target_delete_authorization(
    *, operation: str, requirement: PermissionRequirement
) -> OperationAuthorization:
    return OperationAuthorization.for_requirement(
        admin_id="admin",
        resource_id="children",
        operation=operation,
        principal_id="operator",
        requirement=requirement,
        target_identity=_identity(1),
    )


@pytest.mark.anyio
async def test_destructive_relationship_requires_target_delete_capability_for_exact_operation(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        parent = DeleteParent()
        parent.children.append(DeleteChild(name="child"))
        session.add(parent)
        await session.commit()

    service, relationship_requirement, delete_requirement = await _destructive_service(
        session_factory
    )
    plan = await _destructive_plan(
        service, relationship_requirement, submission="destructive-wrong-op"
    )
    authorization = _relationship_authorization(
        resource_id="parents",
        operation=plan.operation_id,
        parent_identity=_identity(1),
        requirement=relationship_requirement,
    )
    context = _destructive_context(plan.operation_id, relationship_requirement)
    with activate_operation_context(context):
        confirmation = await service.issue_destructive_confirmation(
            plan, authorization=authorization
        )
        confirmed = plan.model_copy(update={"destructive_confirmation": confirmation})
        with pytest.raises(RakitError) as caught:
            await service.execute(
                confirmed,
                authorization=authorization,
                target_delete_authorizations=(
                    _target_delete_authorization(
                        operation="wrong-target-delete-operation", requirement=delete_requirement
                    ),
                ),
            )

    assert caught.value.code == "auth.forbidden"
    async with session_factory() as session:
        assert list((await session.scalars(select(DeleteChild.name))).all()) == ["child"]


@pytest.mark.anyio
async def test_destructive_confirmation_has_a_distinct_one_time_nonce_when_issued_at_same_time(
    session_factory: async_sessionmaker[AsyncSession], monkeypatch: pytest.MonkeyPatch
) -> None:
    async with session_factory() as session:
        parent = DeleteParent()
        parent.children.append(DeleteChild(name="child"))
        session.add(parent)
        await session.commit()

    service, relationship_requirement, _delete_requirement = await _destructive_service(
        session_factory
    )
    plan = await _destructive_plan(service, relationship_requirement, submission="nonce-plan")
    authorization = _relationship_authorization(
        resource_id="parents",
        operation=plan.operation_id,
        parent_identity=_identity(1),
        requirement=relationship_requirement,
    )
    monkeypatch.setattr("rakit_core.crypto.time.time", lambda: 100.0)
    with activate_operation_context(
        _destructive_context(plan.operation_id, relationship_requirement)
    ):
        first = await service.issue_destructive_confirmation(plan, authorization=authorization)
        second = await service.issue_destructive_confirmation(plan, authorization=authorization)

    assert first != second


@pytest.mark.anyio
async def test_independent_sessions_detect_stale_relationship_digest_without_parent_version_change(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        session.add_all((Order(), Tag(name="first"), Tag(name="second")))
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
    entry = service._entry("tags")
    resolver = service._parent_data_source
    async with session_factory() as first_session, session_factory() as second_session:
        first_parent = await resolver.resolve_scoped(first_session, _identity(1))
        second_parent = await resolver.resolve_scoped(second_session, _identity(1))
        assert first_parent is not None and second_parent is not None
        first_token = service._issue_concurrency_token(
            first_parent,
            entry,
            _identity(1),
            await service._state_digest(first_session, first_parent, entry),
        )
        second_token = service._issue_concurrency_token(
            second_parent,
            entry,
            _identity(1),
            await service._state_digest(second_session, second_parent, entry),
        )

    operation = "relationship:orders:tags:add"
    authorization = _relationship_authorization(
        resource_id="orders",
        operation=operation,
        parent_identity=_identity(1),
        requirement=requirement,
    )
    plan_a = RelationshipMutationPlan(
        operation_id=operation,
        parent_resource_id="orders",
        parent_identity=_identity(1),
        relationship_id="tags",
        kind=RelationshipMutationKind.ADD,
        target_identities=(_identity(1),),
        authorization_requirement=requirement,
        concurrency_token=first_token,
        idempotency_token="session-a",
    )
    plan_b = plan_a.model_copy(
        update={
            "target_identities": (_identity(2),),
            "concurrency_token": second_token,
            "idempotency_token": "session-b",
        }
    )
    received: list[RelationshipChanged] = []
    bus = EventBus()
    bus.subscribe(RelationshipChanged, received.append)
    with activate_operation_context(
        OperationContext(
            deadline=None,
            cancellation=CancellationContext(),
            principal=Principal(subject_id="operator", authenticated=True),
            admin_id="admin",
            resource_id="orders",
            operation=operation,
            permission_requirement=requirement,
            events=EventPublisher(bus),
        )
    ):
        await service.execute(plan_a, authorization=authorization)
    with (
        activate_operation_context(
            OperationContext(
                deadline=None,
                cancellation=CancellationContext(),
                principal=Principal(subject_id="operator", authenticated=True),
                admin_id="admin",
                resource_id="orders",
                operation=operation,
                permission_requirement=requirement,
                events=EventPublisher(bus),
            )
        ),
        pytest.raises(RakitError) as caught,
    ):
        await service.execute(plan_b, authorization=authorization)

    assert caught.value.code == "resource.conflict"
    assert len(received) == 1
    async with session_factory() as session:
        order = (await session.scalars(select(Order))).one()
        await session.refresh(order, attribute_names=["tags"])
        assert [tag.name for tag in order.tags] == ["first"]
        # The relationship guard advances the mapped optimistic version even
        # though no application-owned parent scalar field was edited.
        assert order.version == 2


@pytest.mark.anyio
async def test_nested_relationship_mutation_inherits_outer_uow_and_event_publisher(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        session.add_all((Order(), Customer(name="Ada")))
        await session.commit()

    service, requirement = await _customer_service(session_factory)
    operation = "relationship:orders:customer:set"
    authorization = _relationship_authorization(
        resource_id="orders",
        operation=operation,
        parent_identity=_identity(1),
        requirement=requirement,
    )
    received: list[RelationshipChanged] = []
    bus = EventBus()
    bus.subscribe(RelationshipChanged, received.append)

    async def execute_with_outer(*, submission: str, commit: bool) -> None:
        token = await service.issue_concurrency_token(_identity(1), "customer")
        plan = RelationshipMutationPlan(
            operation_id=operation,
            parent_resource_id="orders",
            parent_identity=_identity(1),
            relationship_id="customer",
            kind=RelationshipMutationKind.SET,
            target_identities=(_identity(1),),
            authorization_requirement=requirement,
            concurrency_token=token,
            idempotency_token=submission,
        )
        context = OperationContext(
            deadline=None,
            cancellation=CancellationContext(),
            principal=Principal(subject_id="operator", authenticated=True),
            admin_id="admin",
            resource_id="orders",
            operation=operation,
            permission_requirement=requirement,
            events=EventPublisher(bus),
        )
        with activate_operation_context(context):
            async with SQLAlchemyUnitOfWork(
                session_factory,
                policy=TransactionPolicy.AUTO,
                event_publisher=context.events,
                operation_context=context,
            ) as outer:
                await service.execute(plan, authorization=authorization)
                assert outer.event_publisher is context.events
                if commit:
                    await outer.mark_success()

    await execute_with_outer(submission="nested-rollback", commit=False)
    assert received == []
    async with session_factory() as session:
        assert (await session.scalars(select(Order.customer_id))).one() is None

    await execute_with_outer(submission="nested-commit", commit=True)
    assert len(received) == 1
    async with session_factory() as session:
        assert (await session.scalars(select(Order.customer_id))).one() == 1


@pytest.mark.anyio
async def test_completed_idempotency_replays_without_duplicate_mutation_or_event(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        session.add_all((Order(), Customer(name="Ada"), Customer(name="Grace")))
        await session.commit()

    requirement = PermissionRequirement.all_of("admin.resources.orders.update")
    store = MemoryIdempotencyStore()
    service = SQLAlchemyRelationshipMutationService(
        session_factory=session_factory,
        parent_data_source=_source(Order, session_factory),
        relationships=(_compiled("customer", RelationshipKind.MANY_TO_ONE),),
        target_data_sources={"customers": _source(Customer, session_factory)},
        token_service=TokenService.single_key(
            key_id="test", value=SecretValue("x" * 32), admin_id="admin"
        ),
        concurrency_provider=AttributeVersionProvider("version"),
        idempotency_store=store,
    )
    operation = "relationship:orders:customer:set"
    authorization = _relationship_authorization(
        resource_id="orders",
        operation=operation,
        parent_identity=_identity(1),
        requirement=requirement,
    )
    plan = RelationshipMutationPlan(
        operation_id=operation,
        parent_resource_id="orders",
        parent_identity=_identity(1),
        relationship_id="customer",
        kind=RelationshipMutationKind.SET,
        target_identities=(_identity(1),),
        authorization_requirement=requirement,
        concurrency_token=await service.issue_concurrency_token(_identity(1), "customer"),
        idempotency_token="completed-replay",
    )
    received: list[RelationshipChanged] = []
    bus = EventBus()
    bus.subscribe(RelationshipChanged, received.append)
    context = OperationContext(
        deadline=None,
        cancellation=CancellationContext(),
        principal=Principal(subject_id="operator", authenticated=True),
        admin_id="admin",
        resource_id="orders",
        operation=operation,
        permission_requirement=requirement,
        events=EventPublisher(bus),
    )
    with activate_operation_context(context):
        first = await service.execute(plan, authorization=authorization)
        later = plan.model_copy(
            update={
                "target_identities": (_identity(2),),
                "concurrency_token": first.concurrency_token,
                "idempotency_token": "later-mutation",
            }
        )
        await service.execute(later, authorization=authorization)
        replay = await service.execute(plan, authorization=authorization)
        changed = plan.model_copy(
            update={
                "target_identities": (_identity(2),),
                "concurrency_token": replay.concurrency_token,
            }
        )
        with pytest.raises(RakitError) as caught:
            await service.execute(changed, authorization=authorization)

    assert not first.replayed
    assert replay.replayed
    assert replay.target_identities == (_identity(1),)
    assert caught.value.code == "resource.conflict"
    assert len(received) == 2
    async with session_factory() as session:
        assert (await session.scalars(select(Order.customer_id))).one() == 2


@pytest.mark.anyio
async def test_destructive_relationship_commit_requires_confirmation_and_replays_safely(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        parent = DeleteParent()
        parent.children.append(DeleteChild(name="child"))
        session.add(parent)
        await session.commit()

    service, relationship_requirement, delete_requirement = await _destructive_service(
        session_factory
    )
    plan = await _destructive_plan(
        service, relationship_requirement, submission="destructive-success"
    )
    authorization = _relationship_authorization(
        resource_id="parents",
        operation=plan.operation_id,
        parent_identity=_identity(1),
        requirement=relationship_requirement,
    )
    delete_authorization = _target_delete_authorization(
        operation=f"{plan.operation_id}:target-delete", requirement=delete_requirement
    )
    received: list[RelationshipChanged] = []
    bus = EventBus()
    bus.subscribe(RelationshipChanged, received.append)
    context = OperationContext(
        deadline=None,
        cancellation=CancellationContext(),
        principal=Principal(subject_id="operator", authenticated=True),
        admin_id="admin",
        resource_id="parents",
        operation=plan.operation_id,
        permission_requirement=relationship_requirement,
        events=EventPublisher(bus),
    )
    with activate_operation_context(context), pytest.raises(RakitError) as missing_confirmation:
        await service.execute(
            plan, authorization=authorization, target_delete_authorizations=(delete_authorization,)
        )
    assert missing_confirmation.value.code == "auth.forbidden"

    with activate_operation_context(context):
        confirmation = await service.issue_destructive_confirmation(
            plan, authorization=authorization
        )
        confirmed = plan.model_copy(update={"destructive_confirmation": confirmation})
        result = await service.execute(
            confirmed,
            authorization=authorization,
            target_delete_authorizations=(delete_authorization,),
        )
        replay = await service.execute(
            confirmed,
            authorization=authorization,
            target_delete_authorizations=(delete_authorization,),
        )

    assert result.deleted_target_identities == (_identity(1),)
    assert replay.replayed
    assert len(received) == 1
    assert received[0].deleted_target_identities == (_identity(1),)
    async with session_factory() as session:
        assert list((await session.scalars(select(DeleteChild))).all()) == []
        parent = (await session.scalars(select(DeleteParent))).one()
        await session.refresh(parent, attribute_names=["children"])
        assert parent.children == []


@pytest.mark.anyio
async def test_destructive_confirmation_is_bound_to_the_issuing_session(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        parent = DeleteParent()
        parent.children.append(DeleteChild(name="child"))
        session.add(parent)
        await session.commit()

    service, relationship_requirement, delete_requirement = await _destructive_service(
        session_factory
    )
    plan = await _destructive_plan(service, relationship_requirement, submission="session-bound")
    authorization = _relationship_authorization(
        resource_id="parents",
        operation=plan.operation_id,
        parent_identity=_identity(1),
        requirement=relationship_requirement,
    )
    delete_authorization = _target_delete_authorization(
        operation=f"{plan.operation_id}:target-delete", requirement=delete_requirement
    )
    with activate_operation_context(
        _relationship_context(
            resource_id="parents",
            operation=plan.operation_id,
            requirement=relationship_requirement,
            session_id="session-a",
        )
    ):
        confirmation = await service.issue_destructive_confirmation(
            plan, authorization=authorization
        )
    confirmed = plan.model_copy(update={"destructive_confirmation": confirmation})
    with (
        activate_operation_context(
            _relationship_context(
                resource_id="parents",
                operation=plan.operation_id,
                requirement=relationship_requirement,
                session_id="session-b",
            )
        ),
        pytest.raises(RakitError) as caught,
    ):
        await service.execute(
            confirmed,
            authorization=authorization,
            target_delete_authorizations=(delete_authorization,),
        )

    assert caught.value.code == "auth.forbidden"
    async with session_factory() as session:
        assert list((await session.scalars(select(DeleteChild.name))).all()) == ["child"]


@pytest.mark.anyio
async def test_destructive_confirmation_expiry_is_rejected_before_mutation(
    session_factory: async_sessionmaker[AsyncSession], monkeypatch: pytest.MonkeyPatch
) -> None:
    async with session_factory() as session:
        parent = DeleteParent()
        parent.children.append(DeleteChild(name="child"))
        session.add(parent)
        await session.commit()

    service, relationship_requirement, delete_requirement = await _destructive_service(
        session_factory
    )
    monkeypatch.setattr("rakit_core.crypto.time.time", lambda: 100.0)
    plan = await _destructive_plan(
        service, relationship_requirement, submission="expired-confirmation"
    )
    authorization = _relationship_authorization(
        resource_id="parents",
        operation=plan.operation_id,
        parent_identity=_identity(1),
        requirement=relationship_requirement,
    )
    delete_authorization = _target_delete_authorization(
        operation=f"{plan.operation_id}:target-delete", requirement=delete_requirement
    )
    context = _destructive_context(plan.operation_id, relationship_requirement)
    with activate_operation_context(context):
        confirmation = await service.issue_destructive_confirmation(
            plan, authorization=authorization
        )

    monkeypatch.setattr("rakit_core.crypto.time.time", lambda: 2000.0)
    fresh = plan.model_copy(
        update={
            "concurrency_token": await service.issue_concurrency_token(_identity(1), "children"),
            "destructive_confirmation": confirmation,
        }
    )
    with activate_operation_context(context), pytest.raises(RakitError) as caught:
        await service.execute(
            fresh, authorization=authorization, target_delete_authorizations=(delete_authorization,)
        )

    assert caught.value.code == "auth.forbidden"
    async with session_factory() as session:
        assert list((await session.scalars(select(DeleteChild.name))).all()) == ["child"]


@pytest.mark.anyio
async def test_relationship_execution_replays_through_the_durable_idempotency_store(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    engine = session_factory.kw["bind"]
    assert engine is not None
    async with engine.begin() as connection:
        await connection.run_sync(IdempotencyRecord.metadata.create_all)
    async with session_factory() as session:
        session.add_all((Order(), Customer(name="Ada"), Customer(name="Grace")))
        await session.commit()

    requirement = PermissionRequirement.all_of("admin.resources.orders.update")
    store = SQLAlchemyIdempotencyStore(session_factory)
    service = SQLAlchemyRelationshipMutationService(
        session_factory=session_factory,
        parent_data_source=_source(Order, session_factory),
        relationships=(_compiled("customer", RelationshipKind.MANY_TO_ONE),),
        target_data_sources={"customers": _source(Customer, session_factory)},
        token_service=TokenService.single_key(
            key_id="test", value=SecretValue("x" * 32), admin_id="admin"
        ),
        concurrency_provider=AttributeVersionProvider("version"),
        idempotency_store=store,
    )
    operation = "relationship:orders:customer:set"
    plan = RelationshipMutationPlan(
        operation_id=operation,
        parent_resource_id="orders",
        parent_identity=_identity(1),
        relationship_id="customer",
        kind=RelationshipMutationKind.SET,
        target_identities=(_identity(1),),
        authorization_requirement=requirement,
        concurrency_token=await service.issue_concurrency_token(_identity(1), "customer"),
        idempotency_token="durable-replay",
    )
    authorization = _relationship_authorization(
        resource_id="orders",
        operation=operation,
        parent_identity=_identity(1),
        requirement=requirement,
    )
    received: list[RelationshipChanged] = []
    bus = EventBus()
    bus.subscribe(RelationshipChanged, received.append)
    context = OperationContext(
        deadline=None,
        cancellation=CancellationContext(),
        principal=Principal(subject_id="operator", authenticated=True),
        admin_id="admin",
        resource_id="orders",
        operation=operation,
        permission_requirement=requirement,
        events=EventPublisher(bus),
    )
    with activate_operation_context(context):
        first = await service.execute(plan, authorization=authorization)
        later = plan.model_copy(
            update={
                "target_identities": (_identity(2),),
                "concurrency_token": first.concurrency_token,
                "idempotency_token": "durable-later-mutation",
            }
        )
        await service.execute(later, authorization=authorization)
        replay = await service.execute(plan, authorization=authorization)

    assert not first.replayed
    assert replay.replayed
    assert replay.target_identities == (_identity(1),)
    assert replay.added_target_identities == (_identity(1),)
    assert len(received) == 2
    async with session_factory() as session:
        records = list((await session.scalars(select(IdempotencyRecord))).all())
        assert [record.status for record in records] == [
            IdempotencyStatus.COMPLETED,
            IdempotencyStatus.COMPLETED,
        ]


@pytest.mark.anyio
async def test_uuid_relationship_mutation_uses_canonical_identity_in_execution_and_receipt(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    parent_id, target_id = uuid4(), uuid4()
    async with session_factory() as session:
        session.add_all((UUIDOrder(id=parent_id), UUIDCustomer(id=target_id, name="Ada")))
        await session.commit()

    requirement = PermissionRequirement.all_of("admin.resources.uuid-orders.update")
    definition = RelationshipDefinition(
        relationship_id="customer",
        target_resource_id="uuid_customers",
        label="Customer",
        kind=RelationshipKind.MANY_TO_ONE,
        cardinality=RelationshipCardinality.TO_ONE,
        nullable=True,
        edit_mode=RelationshipEditMode.LINK,
        writable=True,
    )
    compiled = CompiledRelationship(
        source_resource_id="uuid_orders",
        definition=definition,
        mutation_permission=requirement,
        target_delete_permission=None,
        route_path="/uuid-orders/{identity}/_relationships/customer",
    )
    store = MemoryIdempotencyStore()
    service = SQLAlchemyRelationshipMutationService(
        session_factory=session_factory,
        parent_data_source=_source(UUIDOrder, session_factory),
        relationships=(compiled,),
        target_data_sources={"uuid_customers": _source(UUIDCustomer, session_factory)},
        token_service=TokenService.single_key(
            key_id="test", value=SecretValue("x" * 32), admin_id="admin"
        ),
        concurrency_provider=AttributeVersionProvider("version"),
        idempotency_store=store,
    )
    parent_identity, target_identity = _uuid_identity(parent_id), _uuid_identity(target_id)
    operation = "relationship:uuid_orders:customer:set"
    plan = RelationshipMutationPlan(
        operation_id=operation,
        parent_resource_id="uuid_orders",
        parent_identity=parent_identity,
        relationship_id="customer",
        kind=RelationshipMutationKind.SET,
        target_identities=(target_identity,),
        authorization_requirement=requirement,
        concurrency_token=await service.issue_concurrency_token(parent_identity, "customer"),
        idempotency_token="uuid-replay",
    )
    authorization = _relationship_authorization(
        resource_id="uuid_orders",
        operation=operation,
        parent_identity=parent_identity,
        requirement=requirement,
    )
    context = _relationship_context(
        resource_id="uuid_orders", operation=operation, requirement=requirement
    )
    with activate_operation_context(context):
        result = await service.execute(plan, authorization=authorization)
        replay = await service.execute(plan, authorization=authorization)

    assert result.target_identities == (target_identity,)
    assert replay.target_identities == (target_identity,)
    assert replay.replayed
    assert plan.fingerprint


@pytest.mark.anyio
async def test_concurrent_secondary_relationship_writes_have_one_atomic_winner(
    tmp_path,
) -> None:
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'relationship-race.db'}")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        session.add_all((Order(), Tag(name="first"), Tag(name="second")))
        await session.commit()

    requirement = PermissionRequirement.all_of("admin.resources.orders.update")
    service = SQLAlchemyRelationshipMutationService(
        session_factory=factory,
        parent_data_source=_source(Order, factory),
        relationships=(_compiled("tags", RelationshipKind.MANY_TO_MANY),),
        target_data_sources={"tags": _source(Tag, factory)},
        token_service=TokenService.single_key(
            key_id="test", value=SecretValue("x" * 32), admin_id="admin"
        ),
        concurrency_provider=AttributeVersionProvider("version"),
        idempotency_store=MemoryIdempotencyStore(),
    )
    base_token = await service.issue_concurrency_token(_identity(1), "tags")
    operation = "relationship:orders:tags:add"
    authorization = _relationship_authorization(
        resource_id="orders",
        operation=operation,
        parent_identity=_identity(1),
        requirement=requirement,
    )
    barrier = anyio.Event()
    ready = 0
    outcomes: list[str] = []
    received: list[RelationshipChanged] = []
    bus = EventBus()
    bus.subscribe(RelationshipChanged, received.append)

    async def race(target: int) -> None:
        nonlocal ready
        ready += 1
        if ready == 2:
            barrier.set()
        await barrier.wait()
        plan = RelationshipMutationPlan(
            operation_id=operation,
            parent_resource_id="orders",
            parent_identity=_identity(1),
            relationship_id="tags",
            kind=RelationshipMutationKind.ADD,
            target_identities=(_identity(target),),
            authorization_requirement=requirement,
            concurrency_token=base_token,
            idempotency_token=f"race-{target}",
        )
        context = OperationContext(
            deadline=None,
            cancellation=CancellationContext(),
            principal=Principal(subject_id="operator", authenticated=True),
            admin_id="admin",
            resource_id="orders",
            operation=operation,
            permission_requirement=requirement,
            events=EventPublisher(bus),
        )
        with activate_operation_context(context):
            try:
                await service.execute(plan, authorization=authorization)
            except RakitError as exc:
                assert exc.code == "resource.conflict"
                outcomes.append("conflict")
            else:
                outcomes.append("success")

    async with anyio.create_task_group() as group:
        group.start_soon(race, 1)
        group.start_soon(race, 2)

    assert sorted(outcomes) == ["conflict", "success"]
    assert len(received) == 1
    async with factory() as session:
        order = (await session.scalars(select(Order))).one()
        await session.refresh(order, attribute_names=["tags"])
        assert len(order.tags) == 1
        assert order.version == 2
    await engine.dispose()


@pytest.mark.anyio
async def test_plain_delete_cascade_is_not_target_deletion_on_relationship_unlink(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        parent = DeleteCascadeParent()
        parent.children.append(DeleteCascadeChild(name="child"))
        session.add(parent)
        await session.commit()

    requirement = PermissionRequirement.all_of("admin.resources.cascade_parents.update")
    definition = RelationshipDefinition(
        relationship_id="children",
        target_resource_id="cascade_children",
        label="Children",
        kind=RelationshipKind.ONE_TO_MANY,
        cardinality=RelationshipCardinality.TO_MANY,
        edit_mode=RelationshipEditMode.LINK,
        writable=True,
    )
    compiled = CompiledRelationship(
        source_resource_id="cascade_parents",
        definition=definition,
        mutation_permission=requirement,
        target_delete_permission=None,
        route_path="/cascade-parents/{identity}/_relationships/children",
    )
    service = SQLAlchemyRelationshipMutationService(
        session_factory=session_factory,
        parent_data_source=_source(DeleteCascadeParent, session_factory),
        relationships=(compiled,),
        target_data_sources={"cascade_children": _source(DeleteCascadeChild, session_factory)},
        token_service=TokenService.single_key(
            key_id="test", value=SecretValue("x" * 32), admin_id="admin"
        ),
        concurrency_provider=AttributeVersionProvider("version"),
        idempotency_store=MemoryIdempotencyStore(),
    )
    operation = "relationship:cascade_parents:children:remove"
    plan = RelationshipMutationPlan(
        operation_id=operation,
        parent_resource_id="cascade_parents",
        parent_identity=_identity(1),
        relationship_id="children",
        kind=RelationshipMutationKind.REMOVE,
        target_identities=(_identity(1),),
        authorization_requirement=requirement,
        concurrency_token=await service.issue_concurrency_token(_identity(1), "children"),
        idempotency_token="plain-delete-cascade",
    )
    with activate_operation_context(
        _relationship_context(
            resource_id="cascade_parents", operation=operation, requirement=requirement
        )
    ):
        result = await service.execute(
            plan,
            authorization=_relationship_authorization(
                resource_id="cascade_parents",
                operation=operation,
                parent_identity=_identity(1),
                requirement=requirement,
            ),
        )

    assert result.deleted_target_identities == ()
    async with session_factory() as session:
        child = (await session.scalars(select(DeleteCascadeChild))).one()
        assert child.parent_id is None


@pytest.mark.anyio
async def test_destructive_confirmation_rejects_every_bound_context_dimension(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        parent = DeleteParent()
        parent.children.append(DeleteChild(name="child"))
        session.add(parent)
        await session.commit()

    service, relationship_requirement, delete_requirement = await _destructive_service(
        session_factory
    )
    plan = await _destructive_plan(
        service, relationship_requirement, submission="confirmation-bindings"
    )
    authorization = _relationship_authorization(
        resource_id="parents",
        operation=plan.operation_id,
        parent_identity=_identity(1),
        requirement=relationship_requirement,
    )
    delete_authorization = _target_delete_authorization(
        operation=f"{plan.operation_id}:target-delete", requirement=delete_requirement
    )
    context = _relationship_context(
        resource_id="parents",
        operation=plan.operation_id,
        requirement=relationship_requirement,
        session_id="session-a",
    )
    with activate_operation_context(context):
        valid_confirmation = await service.issue_destructive_confirmation(
            plan, authorization=authorization
        )
    claims = service._token_service.verify(
        valid_confirmation, expected_purpose="relationship_destructive_confirmation"
    )
    replacements = {
        "admin_id": "other-admin",
        "principal_id": "other-principal",
        "session_id": "other-session",
        "parent_resource_id": "other-parents",
        "parent_identity": {"id": 2},
        "relationship_id": "other-relationship",
        "kind": RelationshipMutationKind.REPLACE.value,
        "targets": [],
        "relationship_state_digest": "other-snapshot",
        "impact_digest": "other-impact",
    }
    for key, value in replacements.items():
        invalid_claims = {**claims, key: value}
        invalid_confirmation = service._token_service.issue_in(
            "relationship_destructive_confirmation", invalid_claims, timedelta(minutes=15)
        )
        invalid_plan = plan.model_copy(update={"destructive_confirmation": invalid_confirmation})
        with activate_operation_context(context), pytest.raises(RakitError) as caught:
            await service.execute(
                invalid_plan,
                authorization=authorization,
                target_delete_authorizations=(delete_authorization,),
            )
        assert caught.value.code == "auth.forbidden"


@pytest.mark.anyio
async def test_consumed_destructive_confirmation_nonce_cannot_be_claimed_twice(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        parent = DeleteParent()
        parent.children.append(DeleteChild(name="child"))
        session.add(parent)
        await session.commit()

    service, relationship_requirement, delete_requirement = await _destructive_service(
        session_factory
    )
    plan = await _destructive_plan(service, relationship_requirement, submission="nonce-replay")
    authorization = _relationship_authorization(
        resource_id="parents",
        operation=plan.operation_id,
        parent_identity=_identity(1),
        requirement=relationship_requirement,
    )
    delete_authorization = _target_delete_authorization(
        operation=f"{plan.operation_id}:target-delete", requirement=delete_requirement
    )
    context = _destructive_context(plan.operation_id, relationship_requirement)
    with activate_operation_context(context):
        confirmation = await service.issue_destructive_confirmation(
            plan, authorization=authorization
        )
        confirmed = plan.model_copy(update={"destructive_confirmation": confirmation})
        entry = service._entry("children")
        async with SQLAlchemyUnitOfWork(
            session_factory, policy=TransactionPolicy.AUTO, operation_context=context
        ) as uow:
            parent = await service._parent_data_source.resolve_scoped(uow.session, _identity(1))
            assert parent is not None
            digest = await service._state_digest(uow.session, parent, entry)
            await service._verify_destructive_execution(
                uow, confirmed, entry, context, (_identity(1),), (delete_authorization,), digest
            )
            await uow.mark_success()
        async with SQLAlchemyUnitOfWork(
            session_factory, policy=TransactionPolicy.AUTO, operation_context=context
        ) as uow:
            parent = await service._parent_data_source.resolve_scoped(uow.session, _identity(1))
            assert parent is not None
            digest = await service._state_digest(uow.session, parent, entry)
            with pytest.raises(RakitError) as caught:
                await service._verify_destructive_execution(
                    uow,
                    confirmed,
                    entry,
                    context,
                    (_identity(1),),
                    (delete_authorization,),
                    digest,
                )
            assert caught.value.code == "resource.conflict"
