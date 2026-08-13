from collections.abc import AsyncIterator

import pytest
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
