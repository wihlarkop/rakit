from collections.abc import AsyncIterator, Callable
from typing import cast

import pytest
from rakit_core.auth import Principal
from rakit_core.concurrency import AttributeVersionProvider
from rakit_core.config import SecretValue
from rakit_core.crypto import TokenService
from rakit_core.definitions import ResourceFieldPolicy
from rakit_core.errors import ErrorCode, RakitError
from rakit_core.events import EventBus, EventPublisher
from rakit_core.fields import FieldDefinition
from rakit_core.forms import FormSchema
from rakit_core.idempotency import OperationReceipt
from rakit_core.identity import RecordIdentity
from rakit_core.mutations import (
    MutationHooks,
    MutationResult,
    OperationAuthorization,
    OperationAuthorizationSet,
    ResourceCreated,
    ResourceDeleted,
    ResourceMutationPlan,
    ResourceUpdated,
)
from rakit_core.operations import CancellationContext, OperationContext, activate_operation_context
from rakit_core.permissions import PermissionRequirement
from rakit_core.relationship_mutations import (
    ClearRelated,
    CreateRelated,
    DeleteRelated,
    LinkRelated,
    RelationshipChangePlan,
    RelationshipMutationKind,
    RelationshipMutationPlan,
    RelationshipMutationResult,
    ReorderRelated,
    SetRelated,
    UnlinkRelated,
    UpdateAssociationRelated,
    UpdateRelated,
)
from rakit_core.relationships import (
    CompiledRelationship,
    RelationshipCardinality,
    RelationshipDefinition,
    RelationshipDestructivePolicy,
    RelationshipEditMode,
    RelationshipKind,
    RelationshipOrderingDefinition,
)
from rakit_sqlalchemy.datasource import SQLAlchemyDataSource
from rakit_sqlalchemy.mutations import SQLAlchemyMutationService
from rakit_sqlalchemy.relationship_mutations import SQLAlchemyRelationshipMutationService
from sqlalchemy import ForeignKey, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class Customer(Base):
    __tablename__ = "graph_mutation_customers"

    id: Mapped[int] = mapped_column(primary_key=True)
    version: Mapped[int] = mapped_column(default=1)
    name: Mapped[str]


class Parent(Base):
    __tablename__ = "graph_mutation_parents"

    id: Mapped[int] = mapped_column(primary_key=True)
    version: Mapped[int] = mapped_column(default=1)
    name: Mapped[str]
    customer_id: Mapped[int | None] = mapped_column(ForeignKey("graph_mutation_customers.id"))
    customer: Mapped[Customer | None] = relationship()
    children: Mapped[list["Child"]] = relationship(
        back_populates="parent", order_by="Child.position"
    )


class Child(Base):
    __tablename__ = "graph_mutation_children"

    id: Mapped[int] = mapped_column(primary_key=True)
    version: Mapped[int] = mapped_column(default=1)
    parent_id: Mapped[int | None] = mapped_column(ForeignKey("graph_mutation_parents.id"))
    name: Mapped[str]
    position: Mapped[int] = mapped_column(default=0)
    parent: Mapped[Parent | None] = relationship(back_populates="children")


class AssociationParent(Base):
    __tablename__ = "graph_mutation_association_parents"

    id: Mapped[int] = mapped_column(primary_key=True)
    version: Mapped[int] = mapped_column(default=1)
    name: Mapped[str]
    enrollments: Mapped[list["AssociationEnrollment"]] = relationship(
        back_populates="parent", cascade="all, delete-orphan"
    )


class AssociationCourse(Base):
    __tablename__ = "graph_mutation_association_courses"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str]


class AssociationEnrollment(Base):
    __tablename__ = "graph_mutation_association_enrollments"

    id: Mapped[int] = mapped_column(primary_key=True)
    parent_id: Mapped[int] = mapped_column(ForeignKey("graph_mutation_association_parents.id"))
    course_id: Mapped[int] = mapped_column(ForeignKey("graph_mutation_association_courses.id"))
    grade: Mapped[str]
    parent: Mapped[AssociationParent] = relationship(back_populates="enrollments")
    course: Mapped[AssociationCourse] = relationship()


class RequiredParent(Base):
    __tablename__ = "graph_mutation_required_parents"

    id: Mapped[int] = mapped_column(primary_key=True)
    version: Mapped[int] = mapped_column(default=1)
    name: Mapped[str]
    children: Mapped[list["RequiredChild"]] = relationship(back_populates="parent")


class RequiredChild(Base):
    __tablename__ = "graph_mutation_required_children"

    id: Mapped[int] = mapped_column(primary_key=True)
    version: Mapped[int] = mapped_column(default=1)
    parent_id: Mapped[int] = mapped_column(
        ForeignKey("graph_mutation_required_parents.id"), nullable=False
    )
    name: Mapped[str]
    parent: Mapped[RequiredParent] = relationship(back_populates="children")


class OrphanParent(Base):
    __tablename__ = "graph_mutation_orphan_parents"

    id: Mapped[int] = mapped_column(primary_key=True)
    version: Mapped[int] = mapped_column(default=1)
    name: Mapped[str]
    child: Mapped["OrphanChild | None"] = relationship(
        back_populates="parent", cascade="all, delete-orphan", single_parent=True
    )


class OrphanChild(Base):
    __tablename__ = "graph_mutation_orphan_children"

    id: Mapped[int] = mapped_column(primary_key=True)
    parent_id: Mapped[int | None] = mapped_column(
        ForeignKey("graph_mutation_orphan_parents.id"), nullable=True
    )
    name: Mapped[str]
    parent: Mapped[OrphanParent | None] = relationship(back_populates="child")


class MemoryIdempotencyStore:
    def __init__(self) -> None:
        self.claims: dict[str, tuple[str, OperationReceipt | None]] = {}
        self._tokens: dict[int, str] = {}
        self._next = 1

    async def begin(self, token_hash: str, *, fingerprint: str):
        from rakit_core.idempotency import IdempotencyReservation, IdempotencyStatus

        existing = self.claims.get(token_hash)
        if existing is not None:
            existing_fingerprint, receipt = existing
            if existing_fingerprint != fingerprint:
                raise ValueError("fingerprint mismatch")
            return IdempotencyReservation(
                reservation_id=1,
                status=(
                    IdempotencyStatus.COMPLETED
                    if receipt is not None
                    else IdempotencyStatus.IN_PROGRESS
                ),
                completed_receipt=receipt,
                claimed=False,
            )
        reservation = IdempotencyReservation(self._next, IdempotencyStatus.IN_PROGRESS)
        self._next += 1
        self._tokens[reservation.reservation_id] = token_hash
        self.claims[token_hash] = (fingerprint, None)
        return reservation

    async def complete(self, reservation, receipt) -> None:
        key = self._tokens[reservation.reservation_id]
        fingerprint, _ = self.claims[key]
        self.claims[key] = (fingerprint, receipt)

    async def release(self, reservation) -> None:
        key = self._tokens.get(reservation.reservation_id)
        if key is not None:
            self.claims.pop(key, None)

    async def fail_final(self, reservation) -> None:
        return None


def _identity(value: int) -> RecordIdentity:
    return RecordIdentity(values={"id": value})


def _source(model: type[object], factory: async_sessionmaker[AsyncSession]) -> SQLAlchemyDataSource:
    return SQLAlchemyDataSource(
        model=model,
        session_factory=factory,
        field_policy=ResourceFieldPolicy(list_fields=("id",), detail_fields=("id",)),
    )


@pytest.fixture
async def session_factory() -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    yield async_sessionmaker(engine, expire_on_commit=False)
    await engine.dispose()


def _services(
    factory: async_sessionmaker[AsyncSession],
    *,
    allow_child_delete: bool = False,
    parent_parser: Callable[[object], object] | None = None,
    child_hooks: MutationHooks | None = None,
) -> tuple[
    SQLAlchemyMutationService, SQLAlchemyMutationService, SQLAlchemyRelationshipMutationService
]:
    token_service = TokenService.single_key(
        key_id="graph", value=SecretValue("x" * 32), admin_id="admin"
    )
    store = MemoryIdempotencyStore()
    parent_writer = SQLAlchemyMutationService(
        model=Parent,
        session_factory=factory,
        form_schema=FormSchema(
            fields=(FieldDefinition(field_id="name", python_type=str, parser=parent_parser),)
        ),
        writable_fields=("name",),
        identity_fields=("id",),
        resource_id="parents",
        token_service=token_service,
        concurrency_provider=AttributeVersionProvider("version"),
        graph_idempotency_store=store,
    )
    child_writer = SQLAlchemyMutationService(
        model=Child,
        session_factory=factory,
        form_schema=FormSchema(fields=(FieldDefinition(field_id="name", python_type=str),)),
        writable_fields=("name",),
        identity_fields=("id",),
        resource_id="children",
        token_service=token_service,
        concurrency_provider=AttributeVersionProvider("version"),
        delete_nonce_store=store,
        hooks=child_hooks,
    )
    requirement = PermissionRequirement.all_of("admin.resources.parents.update")
    definition = RelationshipDefinition(
        relationship_id="children",
        target_resource_id="children",
        label="Children",
        kind=RelationshipKind.ONE_TO_MANY,
        cardinality=RelationshipCardinality.TO_MANY,
        nullable=True,
        ordered=True,
        ordering=RelationshipOrderingDefinition(position_field="position"),
        edit_mode=RelationshipEditMode.INLINE,
        writable=True,
        destructive_policy=RelationshipDestructivePolicy(allow_child_delete=allow_child_delete),
    )
    relationship = CompiledRelationship(
        source_resource_id="parents",
        definition=definition,
        mutation_permission=requirement,
        target_delete_permission=(
            PermissionRequirement.all_of("admin.resources.children.delete")
            if allow_child_delete
            else None
        ),
        target_create_permission=PermissionRequirement.all_of("admin.resources.children.create"),
        target_update_permission=PermissionRequirement.all_of("admin.resources.children.update"),
        ordering=definition.ordering,
        route_path="/parents/{identity}/_relationships/children",
    )
    relationship_writer = SQLAlchemyRelationshipMutationService(
        session_factory=factory,
        parent_data_source=_source(Parent, factory),
        relationships=(relationship,),
        target_data_sources={"children": _source(Child, factory)},
        target_mutation_services={"children": child_writer},
        token_service=token_service,
        concurrency_provider=AttributeVersionProvider("version"),
        idempotency_store=store,
    )
    parent_writer.bind_graph_relationship_service(relationship_writer, idempotency_store=store)
    return parent_writer, child_writer, relationship_writer


def _to_one_services(
    factory: async_sessionmaker[AsyncSession],
) -> tuple[SQLAlchemyMutationService, SQLAlchemyRelationshipMutationService]:
    token_service = TokenService.single_key(
        key_id="graph", value=SecretValue("x" * 32), admin_id="admin"
    )
    store = MemoryIdempotencyStore()
    parent_writer = SQLAlchemyMutationService(
        model=Parent,
        session_factory=factory,
        form_schema=FormSchema(fields=(FieldDefinition(field_id="name", python_type=str),)),
        writable_fields=("name",),
        identity_fields=("id",),
        resource_id="parents",
        token_service=token_service,
        concurrency_provider=AttributeVersionProvider("version"),
        graph_idempotency_store=store,
    )
    requirement = PermissionRequirement.all_of("admin.resources.parents.update")
    definition = RelationshipDefinition(
        relationship_id="customer",
        target_resource_id="customers",
        label="Customer",
        kind=RelationshipKind.MANY_TO_ONE,
        cardinality=RelationshipCardinality.TO_ONE,
        nullable=True,
        edit_mode=RelationshipEditMode.LINK,
        writable=True,
    )
    relationship_writer = SQLAlchemyRelationshipMutationService(
        session_factory=factory,
        parent_data_source=_source(Parent, factory),
        relationships=(
            CompiledRelationship(
                source_resource_id="parents",
                definition=definition,
                mutation_permission=requirement,
                target_delete_permission=None,
                route_path="/parents/{identity}/_relationships/customer",
            ),
        ),
        target_data_sources={"customers": _source(Customer, factory)},
        token_service=token_service,
        concurrency_provider=AttributeVersionProvider("version"),
        idempotency_store=store,
    )
    parent_writer.bind_graph_relationship_service(relationship_writer, idempotency_store=store)
    return parent_writer, relationship_writer


def _association_services(
    factory: async_sessionmaker[AsyncSession],
) -> tuple[SQLAlchemyMutationService, SQLAlchemyRelationshipMutationService]:
    token_service = TokenService.single_key(
        key_id="graph", value=SecretValue("x" * 32), admin_id="admin"
    )
    store = MemoryIdempotencyStore()
    parent_writer = SQLAlchemyMutationService(
        model=AssociationParent,
        session_factory=factory,
        form_schema=FormSchema(fields=(FieldDefinition(field_id="name", python_type=str),)),
        writable_fields=("name",),
        identity_fields=("id",),
        resource_id="association_parents",
        token_service=token_service,
        concurrency_provider=AttributeVersionProvider("version"),
        graph_idempotency_store=store,
    )
    requirement = PermissionRequirement.all_of("admin.resources.association_parents.update")
    definition = RelationshipDefinition(
        relationship_id="enrollments",
        target_resource_id="enrollments",
        association_target_resource_id="courses",
        association_fields=("grade",),
        label="Courses",
        kind=RelationshipKind.ASSOCIATION_OBJECT,
        cardinality=RelationshipCardinality.TO_MANY,
        nullable=True,
        edit_mode=RelationshipEditMode.INLINE,
        writable=True,
    )
    relationship_writer = SQLAlchemyRelationshipMutationService(
        session_factory=factory,
        parent_data_source=_source(AssociationParent, factory),
        relationships=(
            CompiledRelationship(
                source_resource_id="association_parents",
                definition=definition,
                mutation_permission=requirement,
                target_delete_permission=None,
                route_path="/association-parents/{identity}/_relationships/enrollments",
            ),
        ),
        target_data_sources={
            "enrollments": _source(AssociationEnrollment, factory),
            "courses": _source(AssociationCourse, factory),
        },
        token_service=token_service,
        concurrency_provider=AttributeVersionProvider("version"),
        idempotency_store=store,
    )
    parent_writer.bind_graph_relationship_service(relationship_writer, idempotency_store=store)
    return parent_writer, relationship_writer


def _required_fk_services(
    factory: async_sessionmaker[AsyncSession], *, child_hooks: MutationHooks | None = None
) -> tuple[SQLAlchemyMutationService, SQLAlchemyRelationshipMutationService]:
    token_service = TokenService.single_key(
        key_id="graph", value=SecretValue("x" * 32), admin_id="admin"
    )
    store = MemoryIdempotencyStore()
    parent_writer = SQLAlchemyMutationService(
        model=RequiredParent,
        session_factory=factory,
        form_schema=FormSchema(fields=(FieldDefinition(field_id="name", python_type=str),)),
        writable_fields=("name",),
        identity_fields=("id",),
        resource_id="required_parents",
        token_service=token_service,
        concurrency_provider=AttributeVersionProvider("version"),
        graph_idempotency_store=store,
    )
    child_writer = SQLAlchemyMutationService(
        model=RequiredChild,
        session_factory=factory,
        form_schema=FormSchema(fields=(FieldDefinition(field_id="name", python_type=str),)),
        writable_fields=("name",),
        identity_fields=("id",),
        resource_id="required_children",
        token_service=token_service,
        concurrency_provider=AttributeVersionProvider("version"),
        hooks=child_hooks,
    )
    requirement = PermissionRequirement.all_of("admin.resources.required_parents.update")
    definition = RelationshipDefinition(
        relationship_id="children",
        target_resource_id="required_children",
        label="Children",
        kind=RelationshipKind.ONE_TO_MANY,
        cardinality=RelationshipCardinality.TO_MANY,
        nullable=False,
        edit_mode=RelationshipEditMode.INLINE,
        writable=True,
    )
    relationship_writer = SQLAlchemyRelationshipMutationService(
        session_factory=factory,
        parent_data_source=_source(RequiredParent, factory),
        relationships=(
            CompiledRelationship(
                source_resource_id="required_parents",
                definition=definition,
                mutation_permission=requirement,
                target_delete_permission=None,
                target_create_permission=PermissionRequirement.all_of(
                    "admin.resources.required_children.create"
                ),
                route_path="/required-parents/{identity}/_relationships/children",
            ),
        ),
        target_data_sources={"required_children": _source(RequiredChild, factory)},
        target_mutation_services={"required_children": child_writer},
        token_service=token_service,
        concurrency_provider=AttributeVersionProvider("version"),
        idempotency_store=store,
    )
    parent_writer.bind_graph_relationship_service(relationship_writer, idempotency_store=store)
    return parent_writer, relationship_writer


def _orphan_set_services(
    factory: async_sessionmaker[AsyncSession],
) -> tuple[SQLAlchemyMutationService, SQLAlchemyRelationshipMutationService]:
    token_service = TokenService.single_key(
        key_id="graph", value=SecretValue("x" * 32), admin_id="admin"
    )
    store = MemoryIdempotencyStore()
    parent_writer = SQLAlchemyMutationService(
        model=OrphanParent,
        session_factory=factory,
        form_schema=FormSchema(fields=(FieldDefinition(field_id="name", python_type=str),)),
        writable_fields=("name",),
        identity_fields=("id",),
        resource_id="orphan_parents",
        token_service=token_service,
        concurrency_provider=AttributeVersionProvider("version"),
        graph_idempotency_store=store,
    )
    relationship_requirement = PermissionRequirement.all_of("admin.resources.orphan_parents.update")
    delete_requirement = PermissionRequirement.all_of("admin.resources.orphan_children.delete")
    definition = RelationshipDefinition(
        relationship_id="child",
        target_resource_id="orphan_children",
        label="Child",
        kind=RelationshipKind.ONE_TO_ONE,
        cardinality=RelationshipCardinality.TO_ONE,
        nullable=True,
        edit_mode=RelationshipEditMode.LINK,
        writable=True,
        destructive_policy=RelationshipDestructivePolicy(allow_delete_orphan=True),
    )
    relationship_writer = SQLAlchemyRelationshipMutationService(
        session_factory=factory,
        parent_data_source=_source(OrphanParent, factory),
        relationships=(
            CompiledRelationship(
                source_resource_id="orphan_parents",
                definition=definition,
                mutation_permission=relationship_requirement,
                target_delete_permission=delete_requirement,
                route_path="/orphan-parents/{identity}/_relationships/child",
            ),
        ),
        target_data_sources={"orphan_children": _source(OrphanChild, factory)},
        token_service=token_service,
        concurrency_provider=AttributeVersionProvider("version"),
        idempotency_store=store,
    )
    parent_writer.bind_graph_relationship_service(relationship_writer, idempotency_store=store)
    return parent_writer, relationship_writer


def _relationship_capabilities(
    parent: RecordIdentity, change: RelationshipChangePlan
) -> OperationAuthorizationSet:
    requirement = PermissionRequirement.all_of("admin.resources.parents.update")
    root = OperationAuthorization.for_requirement(
        admin_id="admin",
        resource_id="parents",
        operation="update",
        principal_id="operator",
        requirement=requirement,
    )
    return OperationAuthorizationSet(
        root=root,
        capabilities=(
            OperationAuthorization.for_requirement(
                admin_id="admin",
                resource_id="parents",
                operation=change.operation_id,
                principal_id="operator",
                requirement=requirement,
                target_identity=parent,
            ),
        ),
    )


def _capabilities(
    parent: RecordIdentity,
    change: RelationshipChangePlan,
    *,
    child_operation: str | None = None,
    child_identity: RecordIdentity | None = None,
) -> OperationAuthorizationSet:
    root_requirement = PermissionRequirement.all_of("admin.resources.parents.update")
    root = OperationAuthorization.for_requirement(
        admin_id="admin",
        resource_id="parents",
        operation="update",
        principal_id="operator",
        requirement=root_requirement,
    )
    relationship = OperationAuthorization.for_requirement(
        admin_id="admin",
        resource_id="parents",
        operation=change.operation_id,
        principal_id="operator",
        requirement=root_requirement,
        target_identity=parent,
    )
    capabilities = [relationship]
    if child_operation is not None:
        capability = OperationAuthorization.for_requirement(
            admin_id="admin",
            resource_id="children",
            operation=f"{change.operation_id}:{child_operation}",
            principal_id="operator",
            requirement=PermissionRequirement.all_of(
                f"admin.resources.children.{child_operation.removeprefix('target-')}"
            ),
            target_identity=child_identity,
        )
        capabilities.append(capability)
    return OperationAuthorizationSet(root=root, capabilities=tuple(capabilities))


def _create_capabilities(
    change: RelationshipChangePlan,
    *,
    child_operation: str | None = None,
) -> OperationAuthorizationSet:
    root = OperationAuthorization.for_requirement(
        admin_id="admin",
        resource_id="parents",
        operation="create",
        principal_id="operator",
        requirement=PermissionRequirement.all_of("admin.resources.parents.create"),
    )
    relationship = OperationAuthorization.for_requirement(
        admin_id="admin",
        resource_id="parents",
        operation=change.operation_id,
        principal_id="operator",
        requirement=PermissionRequirement.all_of("admin.resources.parents.update"),
    )
    capabilities = [relationship]
    if child_operation is not None:
        capabilities.append(
            OperationAuthorization.for_requirement(
                admin_id="admin",
                resource_id="children",
                operation=f"{change.operation_id}:{child_operation}",
                principal_id="operator",
                requirement=PermissionRequirement.all_of(
                    f"admin.resources.children.{child_operation.removeprefix('target-')}"
                ),
            )
        )
    return OperationAuthorizationSet(root=root, capabilities=tuple(capabilities))


async def _create_graph_call(
    writer: SQLAlchemyMutationService,
    *,
    change: RelationshipChangePlan,
    capabilities: OperationAuthorizationSet,
    submission: str,
):
    root = capabilities.root
    context = OperationContext(
        deadline=None,
        cancellation=CancellationContext(),
        principal=Principal(subject_id="operator", authenticated=True),
        admin_id="admin",
        resource_id="parents",
        operation="create",
        permissions=root.permissions,
        permission_requirement=root.requirement,
    )
    with activate_operation_context(context):
        return await writer.create_graph(
            {"name": "created-parent"},
            relationship_changes=(change,),
            authorizations=capabilities,
            idempotency_token=submission,
        )


async def _graph_call(
    writer: SQLAlchemyMutationService,
    *,
    parent: RecordIdentity,
    scalar_token: str,
    change: RelationshipChangePlan,
    capabilities: OperationAuthorizationSet,
    submission: str,
    name: str = "changed",
    events: EventPublisher | None = None,
):
    root = capabilities.root
    context = OperationContext(
        deadline=None,
        cancellation=CancellationContext(),
        principal=Principal(subject_id="operator", authenticated=True),
        admin_id="admin",
        resource_id="parents",
        operation="update",
        permissions=root.permissions,
        permission_requirement=root.requirement,
        events=events,
    )
    with activate_operation_context(context):
        return await writer.update_graph(
            parent,
            {"name": name},
            relationship_changes=(change,),
            concurrency_token=scalar_token,
            authorizations=capabilities,
            idempotency_token=submission,
        )


@pytest.mark.anyio
async def test_graph_update_creates_child_with_one_parent_version_advance(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        session.add(Parent(name="before"))
        await session.commit()
        parent = (await session.scalars(select(Parent))).one()

    writer, _child_writer, relationships = _services(session_factory)
    parent_identity = _identity(1)
    change = RelationshipChangePlan(
        operation_id="graph:parents:children",
        relationship_id="children",
        steps=(CreateRelated(values={"name": "created"}),),
        authorization_requirement=PermissionRequirement.all_of("admin.resources.parents.update"),
        concurrency_token=await relationships.issue_concurrency_token(parent_identity, "children"),
    )
    result = await _graph_call(
        writer,
        parent=parent_identity,
        scalar_token=writer.issue_update_token(parent),
        change=change,
        capabilities=_capabilities(parent_identity, change, child_operation="target-create"),
        submission="graph-create",
    )

    assert result.identity == parent_identity
    async with session_factory() as session:
        persisted = (await session.scalars(select(Parent))).one()
        children = list((await session.scalars(select(Child))).all())
    assert (persisted.name, persisted.version) == ("changed", 2)
    assert [(child.name, child.parent_id) for child in children] == [("created", 1)]


@pytest.mark.anyio
async def test_graph_update_prepares_parent_fields_exactly_once(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    calls = 0

    def parse_once(value: object) -> object:
        nonlocal calls
        calls += 1
        return str(value).strip()

    async with session_factory() as session:
        session.add_all((Parent(name="before"), Child(name="detached", position=0)))
        await session.commit()
        parent = (await session.scalars(select(Parent))).one()
    writer, _child_writer, relationships = _services(session_factory, parent_parser=parse_once)
    parent_identity = _identity(parent.id)
    change = RelationshipChangePlan(
        operation_id="graph:parents:children:parse-once",
        relationship_id="children",
        steps=(LinkRelated(identity=_identity(1)),),
        authorization_requirement=PermissionRequirement.all_of("admin.resources.parents.update"),
        concurrency_token=await relationships.issue_concurrency_token(parent_identity, "children"),
    )
    await _graph_call(
        writer,
        parent=parent_identity,
        scalar_token=writer.issue_update_token(parent),
        change=change,
        capabilities=_capabilities(parent_identity, change),
        submission="graph-parse-once",
        name=" after ",
    )
    assert calls == 1


@pytest.mark.anyio
async def test_graph_create_flushes_parent_then_creates_child_once_and_replays(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    writer, _child_writer, _relationships = _services(session_factory)
    change = RelationshipChangePlan(
        operation_id="graph:parents:children:create",
        relationship_id="children",
        steps=(CreateRelated(values={"name": "created-child"}),),
        authorization_requirement=PermissionRequirement.all_of("admin.resources.parents.update"),
    )
    capabilities = _create_capabilities(change, child_operation="target-create")
    first = await _create_graph_call(
        writer, change=change, capabilities=capabilities, submission="create-graph"
    )
    replay = await _create_graph_call(
        writer, change=change, capabilities=capabilities, submission="create-graph"
    )

    assert not first.replayed and replay.replayed
    assert first.relationship_results[0].added_target_identities
    async with session_factory() as session:
        parents = list((await session.scalars(select(Parent))).all())
        children = list((await session.scalars(select(Child))).all())
    assert [(parent.name, parent.version) for parent in parents] == [("created-parent", 1)]
    assert [(child.name, child.parent_id) for child in children] == [("created-child", 1)]


@pytest.mark.anyio
async def test_graph_create_links_existing_child_and_rolls_back_on_child_validation_failure(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        session.add(Child(name="detached", position=0))
        await session.commit()
    writer, _child_writer, _relationships = _services(session_factory)
    link = RelationshipChangePlan(
        operation_id="graph:parents:children:create-link",
        relationship_id="children",
        steps=(LinkRelated(identity=_identity(1)),),
        authorization_requirement=PermissionRequirement.all_of("admin.resources.parents.update"),
    )
    await _create_graph_call(
        writer,
        change=link,
        capabilities=_create_capabilities(link),
        submission="create-graph-link",
    )
    invalid = RelationshipChangePlan(
        operation_id="graph:parents:children:create-invalid",
        relationship_id="children",
        steps=(CreateRelated(values={"position": 99}),),
        authorization_requirement=PermissionRequirement.all_of("admin.resources.parents.update"),
    )
    with pytest.raises(RakitError) as caught:
        await _create_graph_call(
            writer,
            change=invalid,
            capabilities=_create_capabilities(invalid, child_operation="target-create"),
            submission="create-graph-invalid",
        )
    assert caught.value.code == ErrorCode.VALIDATION_FAILED
    forbidden = RelationshipChangePlan(
        operation_id="graph:parents:children:create-forbidden",
        relationship_id="children",
        steps=(CreateRelated(values={"name": "forbidden"}),),
        authorization_requirement=PermissionRequirement.all_of("admin.resources.parents.update"),
    )
    with pytest.raises(RakitError) as caught:
        await _create_graph_call(
            writer,
            change=forbidden,
            capabilities=_create_capabilities(forbidden),
            submission="create-graph-forbidden",
        )
    assert caught.value.code == ErrorCode.AUTH_FORBIDDEN
    async with session_factory() as session:
        parents = list((await session.scalars(select(Parent))).all())
        child = (await session.scalars(select(Child))).one()
    assert len(parents) == 1
    assert child.parent_id == parents[0].id


@pytest.mark.anyio
async def test_inline_create_attaches_required_parent_fk_before_first_flush(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    child_phases: list[str] = []
    created_events = 0

    class RecordingPublisher(EventPublisher):
        async def after_commit(self) -> None:
            child_phases.append("event_delivery")
            await super().after_commit()

        def after_rollback(self) -> None:
            child_phases.append("event_rollback")
            super().after_rollback()

    def hook(name: str):
        def record(_value: object) -> None:
            child_phases.append(name)

        return record

    def observe_created(_event: ResourceCreated) -> None:
        nonlocal created_events
        child_phases.append("child_event" if created_events == 0 else "parent_event")
        created_events += 1

    writer, relationships = _required_fk_services(
        session_factory,
        child_hooks=MutationHooks(
            after_execute=(hook("after_execute"),),
            after_flush=(hook("after_flush"),),
            before_commit=(hook("before_commit"),),
            after_commit=(hook("after_commit"),),
            after_rollback=(hook("after_rollback"),),
        ),
    )
    requirement = PermissionRequirement.all_of("admin.resources.required_parents.update")
    root = OperationAuthorization.for_requirement(
        admin_id="admin",
        resource_id="required_parents",
        operation="create",
        principal_id="operator",
        requirement=PermissionRequirement.all_of("admin.resources.required_parents.create"),
    )
    change = RelationshipChangePlan(
        operation_id="graph:required-parents:children:create",
        relationship_id="children",
        steps=(CreateRelated(values={"name": "required-child"}),),
        authorization_requirement=requirement,
    )
    capabilities = OperationAuthorizationSet(
        root=root,
        capabilities=(
            OperationAuthorization.for_requirement(
                admin_id="admin",
                resource_id="required_parents",
                operation=change.operation_id,
                principal_id="operator",
                requirement=requirement,
            ),
            OperationAuthorization.for_requirement(
                admin_id="admin",
                resource_id="required_children",
                operation=f"{change.operation_id}:target-create",
                principal_id="operator",
                requirement=PermissionRequirement.all_of(
                    "admin.resources.required_children.create"
                ),
            ),
        ),
    )
    context = OperationContext(
        deadline=None,
        cancellation=CancellationContext(),
        principal=Principal(subject_id="operator", authenticated=True),
        admin_id="admin",
        resource_id="required_parents",
        operation="create",
        permissions=root.permissions,
        permission_requirement=root.requirement,
        events=RecordingPublisher(EventBus()),
    )
    assert context.events is not None
    context.events.bus.subscribe(ResourceCreated, observe_created)
    with activate_operation_context(context):
        await writer.create_graph(
            {"name": "required-parent"},
            relationship_changes=(change,),
            authorizations=capabilities,
            idempotency_token="required-fk-create",
        )
    async with session_factory() as session:
        parent = (await session.scalars(select(RequiredParent))).one()
        child = (await session.scalars(select(RequiredChild))).one()
    assert child.parent_id == parent.id
    assert child_phases == [
        "after_execute",
        "after_flush",
        "before_commit",
        "event_delivery",
        "child_event",
        "parent_event",
        "after_commit",
    ]

    failing = RelationshipChangePlan(
        operation_id="graph:required-parents:children:create-rollback",
        relationship_id="children",
        steps=(
            CreateRelated(values={"name": "rolled-back-child"}),
            ReorderRelated(identities=(_identity(1),)),
        ),
        authorization_requirement=requirement,
    )
    failing_capabilities = OperationAuthorizationSet(
        root=root,
        capabilities=(
            OperationAuthorization.for_requirement(
                admin_id="admin",
                resource_id="required_parents",
                operation=failing.operation_id,
                principal_id="operator",
                requirement=requirement,
            ),
            OperationAuthorization.for_requirement(
                admin_id="admin",
                resource_id="required_children",
                operation=f"{failing.operation_id}:target-create",
                principal_id="operator",
                requirement=PermissionRequirement.all_of(
                    "admin.resources.required_children.create"
                ),
            ),
        ),
    )
    with activate_operation_context(context), pytest.raises(RakitError):
        await writer.create_graph(
            {"name": "rolled-back-parent"},
            relationship_changes=(failing,),
            authorizations=failing_capabilities,
            idempotency_token="required-fk-rollback",
        )
    async with session_factory() as session:
        parents = list((await session.scalars(select(RequiredParent))).all())
        children = list((await session.scalars(select(RequiredChild))).all())
    assert [(value.name, value.id) for value in parents] == [("required-parent", parent.id)]
    assert [(value.name, value.id) for value in children] == [("required-child", child.id)]
    assert child_phases[-4:] == [
        "after_execute",
        "after_flush",
        "event_rollback",
        "after_rollback",
    ]


@pytest.mark.anyio
async def test_graph_to_one_set_and_clear_share_the_parent_uow(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        session.add_all((Parent(name="before"), Customer(name="Ada")))
        await session.commit()
        parent = (await session.scalars(select(Parent))).one()

    writer, relationships = _to_one_services(session_factory)
    parent_identity = _identity(parent.id)
    set_change = RelationshipChangePlan(
        operation_id="graph:parents:customer:set",
        relationship_id="customer",
        steps=(SetRelated(identity=_identity(1)),),
        authorization_requirement=PermissionRequirement.all_of("admin.resources.parents.update"),
        concurrency_token=await relationships.issue_concurrency_token(parent_identity, "customer"),
    )
    await _graph_call(
        writer,
        parent=parent_identity,
        scalar_token=writer.issue_update_token(parent),
        change=set_change,
        capabilities=_relationship_capabilities(parent_identity, set_change),
        submission="to-one-set",
    )
    async with session_factory() as session:
        persisted = (await session.scalars(select(Parent))).one()
        assert (persisted.name, persisted.customer_id, persisted.version) == ("changed", 1, 2)
        clear_token = writer.issue_update_token(persisted)
    clear_change = RelationshipChangePlan(
        operation_id="graph:parents:customer:clear",
        relationship_id="customer",
        steps=(ClearRelated(),),
        authorization_requirement=PermissionRequirement.all_of("admin.resources.parents.update"),
        concurrency_token=await relationships.issue_concurrency_token(parent_identity, "customer"),
    )
    await _graph_call(
        writer,
        parent=parent_identity,
        scalar_token=clear_token,
        change=clear_change,
        capabilities=_relationship_capabilities(parent_identity, clear_change),
        submission="to-one-clear",
        name="cleared",
    )
    async with session_factory() as session:
        persisted = (await session.scalars(select(Parent))).one()
    assert (persisted.name, persisted.customer_id, persisted.version) == ("cleared", None, 3)

    set_then_fail = RelationshipChangePlan(
        operation_id="graph:parents:customer:set-rollback",
        relationship_id="customer",
        steps=(SetRelated(identity=_identity(1)), ReorderRelated(identities=(_identity(1),))),
        authorization_requirement=PermissionRequirement.all_of("admin.resources.parents.update"),
        concurrency_token=await relationships.issue_concurrency_token(parent_identity, "customer"),
    )
    with pytest.raises(RakitError) as caught:
        await _graph_call(
            writer,
            parent=parent_identity,
            scalar_token=writer.issue_update_token(persisted),
            change=set_then_fail,
            capabilities=_relationship_capabilities(parent_identity, set_then_fail),
            submission="to-one-set-rollback",
            name="would-set",
        )
    assert caught.value.code == ErrorCode.VALIDATION_FAILED
    async with session_factory() as session:
        persisted = (await session.scalars(select(Parent))).one()
    assert (persisted.name, persisted.customer_id, persisted.version) == ("cleared", None, 3)

    async with session_factory() as session:
        persisted = (await session.scalars(select(Parent))).one()
        persisted.customer = (await session.scalars(select(Customer))).one()
        await session.commit()
        await session.refresh(persisted)
    clear_then_fail = RelationshipChangePlan(
        operation_id="graph:parents:customer:clear-rollback",
        relationship_id="customer",
        steps=(ClearRelated(), ReorderRelated(identities=(_identity(1),))),
        authorization_requirement=PermissionRequirement.all_of("admin.resources.parents.update"),
        concurrency_token=await relationships.issue_concurrency_token(parent_identity, "customer"),
    )
    with pytest.raises(RakitError) as caught:
        await _graph_call(
            writer,
            parent=parent_identity,
            scalar_token=writer.issue_update_token(persisted),
            change=clear_then_fail,
            capabilities=_relationship_capabilities(parent_identity, clear_then_fail),
            submission="to-one-clear-rollback",
            name="would-clear",
        )
    assert caught.value.code == ErrorCode.VALIDATION_FAILED
    async with session_factory() as session:
        persisted = (await session.scalars(select(Parent))).one()
    assert (persisted.name, persisted.customer_id, persisted.version) == ("cleared", 1, 3)


@pytest.mark.anyio
async def test_graph_create_can_set_a_to_one_target_after_parent_flush(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        session.add(Customer(name="Ada"))
        await session.commit()
    writer, _relationships = _to_one_services(session_factory)
    change = RelationshipChangePlan(
        operation_id="graph:parents:customer:create-set",
        relationship_id="customer",
        steps=(SetRelated(identity=_identity(1)),),
        authorization_requirement=PermissionRequirement.all_of("admin.resources.parents.update"),
    )
    result = await _create_graph_call(
        writer,
        change=change,
        capabilities=_create_capabilities(change),
        submission="create-graph-set",
    )
    async with session_factory() as session:
        persisted = (await session.scalars(select(Parent))).one()
    assert result.identity == _identity(persisted.id)
    assert persisted.customer_id == 1


@pytest.mark.anyio
async def test_graph_set_matches_standalone_delete_orphan_confirmation_semantics(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        parent = OrphanParent(name="before", child=OrphanChild(name="old"))
        replacement = OrphanChild(name="replacement")
        session.add_all((parent, replacement))
        await session.commit()
        old = parent.child
        assert old is not None

    writer, relationships = _orphan_set_services(session_factory)
    parent_identity = _identity(parent.id)
    relationship_requirement = PermissionRequirement.all_of("admin.resources.orphan_parents.update")
    delete_requirement = PermissionRequirement.all_of("admin.resources.orphan_children.delete")
    operation = "graph:orphan-parents:child:set"
    relationship_token = await relationships.issue_concurrency_token(parent_identity, "child")
    change = RelationshipChangePlan(
        operation_id=operation,
        relationship_id="child",
        steps=(SetRelated(identity=_identity(replacement.id)),),
        authorization_requirement=relationship_requirement,
        concurrency_token=relationship_token,
    )
    root = OperationAuthorization.for_requirement(
        admin_id="admin",
        resource_id="orphan_parents",
        operation="update",
        principal_id="operator",
        requirement=relationship_requirement,
    )
    relationship_capability = OperationAuthorization.for_requirement(
        admin_id="admin",
        resource_id="orphan_parents",
        operation=operation,
        principal_id="operator",
        requirement=relationship_requirement,
        target_identity=parent_identity,
    )
    delete_capability = OperationAuthorization.for_requirement(
        admin_id="admin",
        resource_id="orphan_children",
        operation=f"{operation}:target-delete",
        principal_id="operator",
        requirement=delete_requirement,
        target_identity=_identity(old.id),
    )
    capabilities = OperationAuthorizationSet(
        root=root, capabilities=(relationship_capability, delete_capability)
    )
    graph_context = OperationContext(
        deadline=None,
        cancellation=CancellationContext(),
        principal=Principal(subject_id="operator", authenticated=True),
        admin_id="admin",
        resource_id="orphan_parents",
        operation="update",
        permissions=root.permissions,
        permission_requirement=root.requirement,
        session_id="graph-session",
    )
    with activate_operation_context(graph_context), pytest.raises(RakitError) as caught:
        await writer.update_graph(
            parent_identity,
            {"name": "would-set"},
            relationship_changes=(change,),
            concurrency_token=writer.issue_update_token(parent),
            authorizations=capabilities,
            idempotency_token="orphan-set-missing-confirmation",
        )
    assert caught.value.code == ErrorCode.AUTH_FORBIDDEN

    standalone_plan = RelationshipMutationPlan(
        operation_id=operation,
        parent_resource_id="orphan_parents",
        parent_identity=parent_identity,
        relationship_id="child",
        kind=RelationshipMutationKind.SET,
        target_identities=(_identity(replacement.id),),
        authorization_requirement=relationship_requirement,
        concurrency_token=relationship_token,
    )
    relationship_context = OperationContext(
        deadline=None,
        cancellation=CancellationContext(),
        principal=Principal(subject_id="operator", authenticated=True),
        admin_id="admin",
        resource_id="orphan_parents",
        operation=operation,
        permissions=relationship_capability.permissions,
        permission_requirement=relationship_requirement,
        session_id="graph-session",
    )
    with activate_operation_context(relationship_context):
        confirmation = await relationships.issue_destructive_confirmation(
            standalone_plan, authorization=relationship_capability
        )
    confirmed = change.model_copy(update={"destructive_confirmation": confirmation})
    with activate_operation_context(graph_context):
        result = await writer.update_graph(
            parent_identity,
            {"name": "after"},
            relationship_changes=(confirmed,),
            concurrency_token=writer.issue_update_token(parent),
            authorizations=capabilities,
            idempotency_token="orphan-set-confirmed",
        )
    relation_result = cast(RelationshipMutationResult, result.relationship_results[0])
    assert relation_result.deleted_target_identities == (_identity(old.id),)
    async with session_factory() as session:
        persisted = (await session.scalars(select(OrphanParent))).one()
        await session.refresh(persisted, attribute_names=["child"])
        children = list((await session.scalars(select(OrphanChild))).all())
    assert persisted.child is not None
    assert (persisted.name, persisted.child.id) == ("after", replacement.id)
    assert [child.id for child in children] == [replacement.id]


@pytest.mark.anyio
async def test_graph_association_scalar_update_uses_the_phase_two_edge_allowlist(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        course = AssociationCourse(name="Math")
        parent = AssociationParent(name="before")
        parent.enrollments.append(AssociationEnrollment(course=course, grade="B"))
        session.add(parent)
        await session.commit()
        enrollment = parent.enrollments[0]

    writer, relationships = _association_services(session_factory)
    parent_identity = _identity(parent.id)
    requirement = PermissionRequirement.all_of("admin.resources.association_parents.update")
    change = RelationshipChangePlan(
        operation_id="graph:association-parents:enrollments:update",
        relationship_id="enrollments",
        steps=(
            UpdateAssociationRelated(
                target_identity=_identity(enrollment.course_id),
                association_identity=_identity(enrollment.id),
                values={"grade": "A"},
            ),
        ),
        authorization_requirement=requirement,
        concurrency_token=await relationships.issue_concurrency_token(
            parent_identity, "enrollments"
        ),
    )
    root = OperationAuthorization.for_requirement(
        admin_id="admin",
        resource_id="association_parents",
        operation="update",
        principal_id="operator",
        requirement=requirement,
    )
    capabilities = OperationAuthorizationSet(
        root=root,
        capabilities=(
            OperationAuthorization.for_requirement(
                admin_id="admin",
                resource_id="association_parents",
                operation=change.operation_id,
                principal_id="operator",
                requirement=requirement,
                target_identity=parent_identity,
            ),
        ),
    )
    context = OperationContext(
        deadline=None,
        cancellation=CancellationContext(),
        principal=Principal(subject_id="operator", authenticated=True),
        admin_id="admin",
        resource_id="association_parents",
        operation="update",
        permissions=root.permissions,
        permission_requirement=root.requirement,
    )
    with activate_operation_context(context):
        await writer.update_graph(
            parent_identity,
            {"name": "after"},
            relationship_changes=(change,),
            concurrency_token=writer.issue_update_token(parent),
            authorizations=capabilities,
            idempotency_token="association-update",
        )
    async with session_factory() as session:
        persisted_parent = (await session.scalars(select(AssociationParent))).one()
        persisted_edge = (await session.scalars(select(AssociationEnrollment))).one()
    assert (persisted_parent.name, persisted_parent.version, persisted_edge.grade) == (
        "after",
        2,
        "A",
    )

    async with session_factory() as session:
        parent = (await session.scalars(select(AssociationParent))).one()
    failing = RelationshipChangePlan(
        operation_id="graph:association-parents:enrollments:rollback",
        relationship_id="enrollments",
        steps=(
            UpdateAssociationRelated(
                target_identity=_identity(enrollment.course_id), values={"grade": "C"}
            ),
            ReorderRelated(identities=(_identity(enrollment.course_id),)),
        ),
        authorization_requirement=requirement,
        concurrency_token=await relationships.issue_concurrency_token(
            parent_identity, "enrollments"
        ),
    )
    failing_capabilities = OperationAuthorizationSet(
        root=root,
        capabilities=(
            OperationAuthorization.for_requirement(
                admin_id="admin",
                resource_id="association_parents",
                operation=failing.operation_id,
                principal_id="operator",
                requirement=requirement,
                target_identity=parent_identity,
            ),
        ),
    )
    with activate_operation_context(context), pytest.raises(RakitError) as caught:
        await writer.update_graph(
            parent_identity,
            {"name": "would-rollback"},
            relationship_changes=(failing,),
            concurrency_token=writer.issue_update_token(parent),
            authorizations=failing_capabilities,
            idempotency_token="association-rollback",
        )
    assert caught.value.code == ErrorCode.VALIDATION_FAILED
    async with session_factory() as session:
        persisted_parent = (await session.scalars(select(AssociationParent))).one()
        persisted_edge = (await session.scalars(select(AssociationEnrollment))).one()
    assert (persisted_parent.name, persisted_parent.version, persisted_edge.grade) == (
        "after",
        2,
        "A",
    )


@pytest.mark.anyio
async def test_graph_child_update_and_reorder_use_scoped_child_writer(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        parent = Parent(name="before")
        parent.children.extend((Child(name="first", position=0), Child(name="second", position=1)))
        session.add(parent)
        await session.commit()
        await session.refresh(parent, attribute_names=["children"])
        first, second = parent.children

    writer, child_writer, relationships = _services(session_factory)
    parent_identity = _identity(1)
    change = RelationshipChangePlan(
        operation_id="graph:parents:children:update",
        relationship_id="children",
        steps=(
            UpdateRelated(
                identity=_identity(first.id),
                values={"name": "renamed"},
                concurrency_token=child_writer.issue_update_token(first),
            ),
            ReorderRelated(identities=(_identity(second.id), _identity(first.id))),
        ),
        authorization_requirement=PermissionRequirement.all_of("admin.resources.parents.update"),
        concurrency_token=await relationships.issue_concurrency_token(parent_identity, "children"),
    )
    capabilities = _capabilities(
        parent_identity,
        change,
        child_operation="target-update",
        child_identity=_identity(first.id),
    )
    await _graph_call(
        writer,
        parent=parent_identity,
        scalar_token=writer.issue_update_token(parent),
        change=change,
        capabilities=capabilities,
        submission="graph-update",
    )

    async with session_factory() as session:
        children = list((await session.scalars(select(Child).order_by(Child.position))).all())
    assert [(child.name, child.position) for child in children] == [("second", 0), ("renamed", 1)]


@pytest.mark.anyio
async def test_nested_child_update_lifecycle_defers_commit_and_runs_rollback_once(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    phases: list[str] = []

    class RecordingPublisher(EventPublisher):
        async def after_commit(self) -> None:
            phases.append("event_delivery")
            await super().after_commit()

        def after_rollback(self) -> None:
            phases.append("event_rollback")
            super().after_rollback()

    def phase(name: str):
        def record(_value: object) -> None:
            phases.append(name)

        return record

    async with session_factory() as session:
        parent = Parent(id=100, name="before")
        parent.children.extend(
            (Child(id=200, name="first", position=0), Child(name="second", position=1))
        )
        session.add(parent)
        await session.commit()
        await session.refresh(parent, attribute_names=["children"])
        first = parent.children[0]
    hooks = MutationHooks(
        before_commit=(phase("child_before_commit"),),
        after_commit=(phase("child_after_commit"),),
        after_rollback=(phase("child_after_rollback"),),
    )
    writer, child_writer, relationships = _services(session_factory, child_hooks=hooks)
    parent_identity = _identity(parent.id)
    child_identity = _identity(first.id)
    bus = EventBus()
    bus.subscribe(
        ResourceUpdated,
        lambda event: phases.append("child_event") if event.identity == child_identity else None,
    )
    events = RecordingPublisher(bus)
    success = RelationshipChangePlan(
        operation_id="graph:parents:children:lifecycle-success",
        relationship_id="children",
        steps=(
            UpdateRelated(
                identity=child_identity,
                values={"name": "updated"},
                concurrency_token=child_writer.issue_update_token(first),
            ),
        ),
        authorization_requirement=PermissionRequirement.all_of("admin.resources.parents.update"),
        concurrency_token=await relationships.issue_concurrency_token(parent_identity, "children"),
    )
    await _graph_call(
        writer,
        parent=parent_identity,
        scalar_token=writer.issue_update_token(parent),
        change=success,
        capabilities=_capabilities(
            parent_identity,
            success,
            child_operation="target-update",
            child_identity=child_identity,
        ),
        submission="child-lifecycle-success",
        events=events,
    )
    assert phases == [
        "child_before_commit",
        "event_delivery",
        "child_event",
        "child_after_commit",
    ]

    async with session_factory() as session:
        parent = (await session.scalars(select(Parent))).one()
        child = (await session.scalars(select(Child).where(Child.id == first.id))).one()
    failure = RelationshipChangePlan(
        operation_id="graph:parents:children:lifecycle-rollback",
        relationship_id="children",
        steps=(
            UpdateRelated(
                identity=child_identity,
                values={"name": "would-rollback"},
                concurrency_token=child_writer.issue_update_token(child),
            ),
            ReorderRelated(identities=(_identity(child.id), _identity(999))),
        ),
        authorization_requirement=PermissionRequirement.all_of("admin.resources.parents.update"),
        concurrency_token=await relationships.issue_concurrency_token(parent_identity, "children"),
    )
    with pytest.raises(RakitError):
        await _graph_call(
            writer,
            parent=parent_identity,
            scalar_token=writer.issue_update_token(parent),
            change=failure,
            capabilities=_capabilities(
                parent_identity,
                failure,
                child_operation="target-update",
                child_identity=child_identity,
            ),
            submission="child-lifecycle-rollback",
            events=events,
        )
    assert phases == [
        "child_before_commit",
        "event_delivery",
        "child_event",
        "child_after_commit",
        "event_rollback",
        "child_after_rollback",
    ]


@pytest.mark.anyio
async def test_nested_child_create_rollback_begins_after_parse_and_runs_once(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    phases: list[str] = []

    def reject_normalize(_plan: object) -> None:
        phases.append("normalize")
        raise RuntimeError("child normalization rejected")

    def rolled_back(_cause: object) -> None:
        phases.append("after_rollback")

    async with session_factory() as session:
        session.add(Parent(name="before"))
        await session.commit()
        parent = (await session.scalars(select(Parent))).one()

    writer, _child_writer, relationships = _services(
        session_factory,
        child_hooks=MutationHooks(normalize=(reject_normalize,), after_rollback=(rolled_back,)),
    )
    parent_identity = _identity(parent.id)
    change = RelationshipChangePlan(
        operation_id="graph:parents:children:create-normalize-failure",
        relationship_id="children",
        steps=(CreateRelated(values={"name": "blocked"}),),
        authorization_requirement=PermissionRequirement.all_of("admin.resources.parents.update"),
        concurrency_token=await relationships.issue_concurrency_token(parent_identity, "children"),
    )
    with pytest.raises(RuntimeError, match="child normalization rejected"):
        await _graph_call(
            writer,
            parent=parent_identity,
            scalar_token=writer.issue_update_token(parent),
            change=change,
            capabilities=_capabilities(parent_identity, change, child_operation="target-create"),
            submission="child-create-normalize-failure",
        )
    assert phases == ["normalize", "after_rollback"]
    async with session_factory() as session:
        persisted_parent = (await session.scalars(select(Parent))).one()
        assert persisted_parent.name == "before"
        assert list((await session.scalars(select(Child))).all()) == []


@pytest.mark.anyio
async def test_nested_child_update_hook_failure_runs_rollback_once(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    phases: list[str] = []

    def reject_pre_event(_plan: object) -> None:
        phases.append("pre_event")
        raise RuntimeError("child pre-event rejected")

    def rolled_back(_cause: object) -> None:
        phases.append("after_rollback")

    async with session_factory() as session:
        parent = Parent(name="before")
        parent.children.append(Child(name="before-child", position=0))
        session.add(parent)
        await session.commit()
        await session.refresh(parent, attribute_names=["children"])
        child = parent.children[0]

    writer, child_writer, relationships = _services(
        session_factory,
        child_hooks=MutationHooks(pre_event=(reject_pre_event,), after_rollback=(rolled_back,)),
    )
    parent_identity = _identity(parent.id)
    child_identity = _identity(child.id)
    change = RelationshipChangePlan(
        operation_id="graph:parents:children:update-pre-event-failure",
        relationship_id="children",
        steps=(
            UpdateRelated(
                identity=child_identity,
                values={"name": "blocked"},
                concurrency_token=child_writer.issue_update_token(child),
            ),
        ),
        authorization_requirement=PermissionRequirement.all_of("admin.resources.parents.update"),
        concurrency_token=await relationships.issue_concurrency_token(parent_identity, "children"),
    )
    with pytest.raises(RuntimeError, match="child pre-event rejected"):
        await _graph_call(
            writer,
            parent=parent_identity,
            scalar_token=writer.issue_update_token(parent),
            change=change,
            capabilities=_capabilities(
                parent_identity,
                change,
                child_operation="target-update",
                child_identity=child_identity,
            ),
            submission="child-update-pre-event-failure",
        )
    assert phases == ["pre_event", "after_rollback"]
    async with session_factory() as session:
        persisted_parent = (await session.scalars(select(Parent))).one()
        persisted_child = (await session.scalars(select(Child))).one()
    assert (persisted_parent.name, persisted_child.name) == ("before", "before-child")


@pytest.mark.anyio
async def test_nested_child_delete_hook_failure_runs_rollback_once(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    phases: list[str] = []

    def reject_pre_event(_identity: object) -> None:
        phases.append("pre_event")
        raise RuntimeError("child delete pre-event rejected")

    def rolled_back(_cause: object) -> None:
        phases.append("after_rollback")

    async with session_factory() as session:
        parent = Parent(name="before")
        parent.children.append(Child(name="delete", position=0))
        session.add(parent)
        await session.commit()
        await session.refresh(parent, attribute_names=["children"])
        child = parent.children[0]

    writer, child_writer, relationships = _services(
        session_factory,
        allow_child_delete=True,
        child_hooks=MutationHooks(pre_event=(reject_pre_event,), after_rollback=(rolled_back,)),
    )
    parent_identity = _identity(parent.id)
    child_identity = _identity(child.id)
    change = RelationshipChangePlan(
        operation_id="graph:parents:children:delete-pre-event-failure",
        relationship_id="children",
        steps=(
            DeleteRelated(
                identity=child_identity,
                confirmation_token=await child_writer.issue_delete_token(child_identity),
            ),
        ),
        authorization_requirement=PermissionRequirement.all_of("admin.resources.parents.update"),
        concurrency_token=await relationships.issue_concurrency_token(parent_identity, "children"),
    )
    with pytest.raises(RuntimeError, match="child delete pre-event rejected"):
        await _graph_call(
            writer,
            parent=parent_identity,
            scalar_token=writer.issue_update_token(parent),
            change=change,
            capabilities=_capabilities(
                parent_identity,
                change,
                child_operation="target-delete",
                child_identity=child_identity,
            ),
            submission="child-delete-pre-event-failure",
        )
    assert phases == ["pre_event", "after_rollback"]
    async with session_factory() as session:
        persisted_parent = (await session.scalars(select(Parent))).one()
        persisted_child = (await session.scalars(select(Child))).one()
    assert (persisted_parent.name, persisted_child.name) == ("before", "delete")


@pytest.mark.anyio
async def test_multiple_nested_child_observers_follow_graph_step_order(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    phases: list[str] = []

    def before_commit(plan: object) -> None:
        phases.append(f"before:{cast(ResourceMutationPlan, plan).values['name']}")

    def after_commit(result: object) -> None:
        record = cast(Child, cast(MutationResult, result).record)
        phases.append(f"after:{record.name}")

    def after_rollback(_cause: object) -> None:
        phases.append("rollback")

    async with session_factory() as session:
        session.add(Parent(name="before"))
        await session.commit()
        parent = (await session.scalars(select(Parent))).one()

    writer, _child_writer, relationships = _services(
        session_factory,
        child_hooks=MutationHooks(
            before_commit=(before_commit,),
            after_commit=(after_commit,),
            after_rollback=(after_rollback,),
        ),
    )
    parent_identity = _identity(parent.id)
    success = RelationshipChangePlan(
        operation_id="graph:parents:children:ordered-observers",
        relationship_id="children",
        steps=(
            CreateRelated(values={"name": "first"}),
            CreateRelated(values={"name": "second"}),
        ),
        authorization_requirement=PermissionRequirement.all_of("admin.resources.parents.update"),
        concurrency_token=await relationships.issue_concurrency_token(parent_identity, "children"),
    )
    await _graph_call(
        writer,
        parent=parent_identity,
        scalar_token=writer.issue_update_token(parent),
        change=success,
        capabilities=_capabilities(parent_identity, success, child_operation="target-create"),
        submission="ordered-child-observers",
    )
    assert phases == ["before:first", "before:second", "after:first", "after:second"]

    async with session_factory() as session:
        current_parent = (await session.scalars(select(Parent))).one()
    failure = RelationshipChangePlan(
        operation_id="graph:parents:children:ordered-observers-rollback",
        relationship_id="children",
        steps=(
            CreateRelated(values={"name": "third"}),
            CreateRelated(values={"name": "fourth"}),
            ReorderRelated(identities=(_identity(999),)),
        ),
        authorization_requirement=PermissionRequirement.all_of("admin.resources.parents.update"),
        concurrency_token=await relationships.issue_concurrency_token(parent_identity, "children"),
    )
    with pytest.raises(RakitError):
        await _graph_call(
            writer,
            parent=parent_identity,
            scalar_token=writer.issue_update_token(current_parent),
            change=failure,
            capabilities=_capabilities(parent_identity, failure, child_operation="target-create"),
            submission="ordered-child-observers-rollback",
        )
    assert phases == [
        "before:first",
        "before:second",
        "after:first",
        "after:second",
        "rollback",
        "rollback",
    ]


@pytest.mark.anyio
async def test_missing_child_capability_rolls_back_parent_and_relationship_work(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        session.add(Parent(name="before"))
        await session.commit()
        parent = (await session.scalars(select(Parent))).one()

    writer, _child_writer, relationships = _services(session_factory)
    parent_identity = _identity(1)
    change = RelationshipChangePlan(
        operation_id="graph:parents:children:forbidden",
        relationship_id="children",
        steps=(CreateRelated(values={"name": "blocked"}),),
        authorization_requirement=PermissionRequirement.all_of("admin.resources.parents.update"),
        concurrency_token=await relationships.issue_concurrency_token(parent_identity, "children"),
    )
    with pytest.raises(RakitError) as caught:
        await _graph_call(
            writer,
            parent=parent_identity,
            scalar_token=writer.issue_update_token(parent),
            change=change,
            capabilities=_capabilities(parent_identity, change),
            submission="graph-forbidden",
        )
    assert caught.value.code == ErrorCode.AUTH_FORBIDDEN
    async with session_factory() as session:
        persisted = (await session.scalars(select(Parent))).one()
        children = list((await session.scalars(select(Child))).all())
    assert (persisted.name, persisted.version, children) == ("before", 1, [])


@pytest.mark.anyio
async def test_invalid_child_fields_and_stale_child_roll_back_parent_update(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        parent = Parent(name="before")
        parent.children.append(Child(name="child", position=0))
        session.add(parent)
        await session.commit()
        await session.refresh(parent, attribute_names=["children"])
        child = parent.children[0]

    writer, child_writer, relationships = _services(session_factory)
    parent_identity = _identity(parent.id)
    invalid = RelationshipChangePlan(
        operation_id="graph:parents:children:invalid",
        relationship_id="children",
        steps=(UpdateRelated(identity=_identity(child.id), values={"position": 99}),),
        authorization_requirement=PermissionRequirement.all_of("admin.resources.parents.update"),
        concurrency_token=await relationships.issue_concurrency_token(parent_identity, "children"),
    )
    with pytest.raises(RakitError) as caught:
        await _graph_call(
            writer,
            parent=parent_identity,
            scalar_token=writer.issue_update_token(parent),
            change=invalid,
            capabilities=_capabilities(
                parent_identity,
                invalid,
                child_operation="target-update",
                child_identity=_identity(child.id),
            ),
            submission="graph-invalid-field",
        )
    assert caught.value.code == ErrorCode.VALIDATION_FAILED

    stale_token = child_writer.issue_update_token(child)
    async with session_factory() as session:
        current = (await session.scalars(select(Child))).one()
        current.version = 2
        await session.commit()
    stale = RelationshipChangePlan(
        operation_id="graph:parents:children:stale",
        relationship_id="children",
        steps=(
            UpdateRelated(
                identity=_identity(child.id),
                values={"name": "stale"},
                concurrency_token=stale_token,
            ),
        ),
        authorization_requirement=PermissionRequirement.all_of("admin.resources.parents.update"),
        concurrency_token=await relationships.issue_concurrency_token(parent_identity, "children"),
    )
    with pytest.raises(RakitError) as caught:
        await _graph_call(
            writer,
            parent=parent_identity,
            scalar_token=writer.issue_update_token(parent),
            change=stale,
            capabilities=_capabilities(
                parent_identity,
                stale,
                child_operation="target-update",
                child_identity=_identity(child.id),
            ),
            submission="graph-stale-child",
        )
    assert caught.value.code == ErrorCode.RESOURCE_CONFLICT
    async with session_factory() as session:
        persisted_parent = (await session.scalars(select(Parent))).one()
        persisted_child = (await session.scalars(select(Child))).one()
    assert (persisted_parent.name, persisted_parent.version, persisted_child.name) == (
        "before",
        1,
        "child",
    )


@pytest.mark.anyio
async def test_reorder_rejects_incomplete_or_foreign_members_without_parent_write(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        parent = Parent(name="before")
        parent.children.extend((Child(name="first", position=0), Child(name="second", position=1)))
        session.add_all((parent, Child(name="foreign", position=0)))
        await session.commit()
        await session.refresh(parent, attribute_names=["children"])

    writer, _child_writer, relationships = _services(session_factory)
    parent_identity = _identity(parent.id)
    invalid = RelationshipChangePlan(
        operation_id="graph:parents:children:bad-order",
        relationship_id="children",
        steps=(ReorderRelated(identities=(_identity(parent.children[0].id), _identity(3))),),
        authorization_requirement=PermissionRequirement.all_of("admin.resources.parents.update"),
        concurrency_token=await relationships.issue_concurrency_token(parent_identity, "children"),
    )
    with pytest.raises(RakitError) as caught:
        await _graph_call(
            writer,
            parent=parent_identity,
            scalar_token=writer.issue_update_token(parent),
            change=invalid,
            capabilities=_capabilities(parent_identity, invalid),
            submission="graph-bad-order",
        )
    assert caught.value.code == ErrorCode.VALIDATION_FAILED
    async with session_factory() as session:
        persisted = (await session.scalars(select(Parent))).one()
        children = list(
            (await session.scalars(select(Child).where(Child.parent_id == parent.id))).all()
        )
    assert (persisted.name, persisted.version) == ("before", 1)
    assert [child.position for child in children] == [0, 1]


@pytest.mark.anyio
async def test_later_reorder_failure_rolls_back_earlier_child_update_and_scalar_change(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        parent = Parent(name="before")
        parent.children.extend((Child(name="first", position=0), Child(name="second", position=1)))
        session.add_all((parent, Child(name="foreign", position=0)))
        await session.commit()
        await session.refresh(parent, attribute_names=["children"])
        first = parent.children[0]

    writer, child_writer, relationships = _services(session_factory)
    parent_identity = _identity(parent.id)
    change = RelationshipChangePlan(
        operation_id="graph:parents:children:rollback",
        relationship_id="children",
        steps=(
            UpdateRelated(
                identity=_identity(first.id),
                values={"name": "would-change"},
                concurrency_token=child_writer.issue_update_token(first),
            ),
            ReorderRelated(identities=(_identity(first.id), _identity(3))),
        ),
        authorization_requirement=PermissionRequirement.all_of("admin.resources.parents.update"),
        concurrency_token=await relationships.issue_concurrency_token(parent_identity, "children"),
    )
    with pytest.raises(RakitError) as caught:
        await _graph_call(
            writer,
            parent=parent_identity,
            scalar_token=writer.issue_update_token(parent),
            change=change,
            capabilities=_capabilities(
                parent_identity,
                change,
                child_operation="target-update",
                child_identity=_identity(first.id),
            ),
            submission="graph-rollback",
        )
    assert caught.value.code == ErrorCode.VALIDATION_FAILED
    async with session_factory() as session:
        persisted_parent = (await session.scalars(select(Parent))).one()
        persisted_child = (await session.scalars(select(Child).where(Child.id == first.id))).one()
    assert (persisted_parent.name, persisted_parent.version, persisted_child.name) == (
        "before",
        1,
        "first",
    )


@pytest.mark.anyio
async def test_explicit_child_delete_requires_its_own_capability_and_confirmation(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        parent = Parent(name="before")
        parent.children.append(Child(name="delete", position=0))
        session.add(parent)
        await session.commit()
        await session.refresh(parent, attribute_names=["children"])
        child = parent.children[0]

    child_phases: list[str] = []

    class RecordingPublisher(EventPublisher):
        async def after_commit(self) -> None:
            child_phases.append("event_delivery")
            await super().after_commit()

        def after_rollback(self) -> None:
            child_phases.append("event_rollback")
            super().after_rollback()

    def phase(name: str):
        def record(_value: object) -> None:
            child_phases.append(name)

        return record

    writer, child_writer, relationships = _services(
        session_factory,
        allow_child_delete=True,
        child_hooks=MutationHooks(
            before_commit=(phase("delete_before_commit"),),
            after_commit=(phase("delete_after_commit"),),
            after_rollback=(phase("delete_after_rollback"),),
        ),
    )
    parent_identity = _identity(parent.id)
    child_identity = _identity(child.id)
    bus = EventBus()
    bus.subscribe(
        ResourceDeleted,
        lambda event: child_phases.append("child_event")
        if event.identity == child_identity
        else None,
    )
    events = RecordingPublisher(bus)
    delete_token = await child_writer.issue_delete_token(child_identity)
    change = RelationshipChangePlan(
        operation_id="graph:parents:children:delete",
        relationship_id="children",
        steps=(
            DeleteRelated(
                identity=child_identity,
                confirmation_token=delete_token,
            ),
        ),
        authorization_requirement=PermissionRequirement.all_of("admin.resources.parents.update"),
        concurrency_token=await relationships.issue_concurrency_token(parent_identity, "children"),
    )
    with pytest.raises(RakitError) as caught:
        await _graph_call(
            writer,
            parent=parent_identity,
            scalar_token=writer.issue_update_token(parent),
            change=change,
            capabilities=_capabilities(parent_identity, change),
            submission="graph-delete-forbidden",
        )
    assert caught.value.code == ErrorCode.AUTH_FORBIDDEN

    async with session_factory() as session:
        current_child = (await session.scalars(select(Child))).one()
        current_child.version = 2
        await session.commit()
        current_parent = (await session.scalars(select(Parent))).one()
    with pytest.raises(RakitError) as caught:
        await _graph_call(
            writer,
            parent=parent_identity,
            scalar_token=writer.issue_update_token(current_parent),
            change=change,
            capabilities=_capabilities(
                parent_identity,
                change,
                child_operation="target-delete",
                child_identity=child_identity,
            ),
            submission="graph-delete-stale",
            events=events,
        )
    assert caught.value.code == ErrorCode.RESOURCE_CONFLICT
    assert child_phases == ["event_rollback", "delete_after_rollback"]

    fresh_token = await child_writer.issue_delete_token(child_identity)
    fresh_change = change.model_copy(
        update={
            "steps": (DeleteRelated(identity=child_identity, confirmation_token=fresh_token),),
            "concurrency_token": await relationships.issue_concurrency_token(
                parent_identity, "children"
            ),
        }
    )

    await _graph_call(
        writer,
        parent=parent_identity,
        scalar_token=writer.issue_update_token(current_parent),
        change=fresh_change,
        capabilities=_capabilities(
            parent_identity,
            fresh_change,
            child_operation="target-delete",
            child_identity=child_identity,
        ),
        submission="graph-delete",
        events=events,
    )
    async with session_factory() as session:
        assert list((await session.scalars(select(Child))).all()) == []
    assert child_phases == [
        "event_rollback",
        "delete_after_rollback",
        "delete_before_commit",
        "event_delivery",
        "child_event",
        "delete_after_commit",
    ]


@pytest.mark.anyio
async def test_graph_link_and_unlink_are_explicit_and_idempotent_replay_is_historical(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        session.add_all((Parent(name="before"), Child(name="detached", position=0)))
        await session.commit()
        parent = (await session.scalars(select(Parent))).one()

    writer, _child_writer, relationships = _services(session_factory)
    parent_identity = _identity(1)
    link = RelationshipChangePlan(
        operation_id="graph:parents:children:link",
        relationship_id="children",
        steps=(LinkRelated(identity=_identity(1)),),
        authorization_requirement=PermissionRequirement.all_of("admin.resources.parents.update"),
        concurrency_token=await relationships.issue_concurrency_token(parent_identity, "children"),
    )
    capabilities = _capabilities(parent_identity, link)
    first = await _graph_call(
        writer,
        parent=parent_identity,
        scalar_token=writer.issue_update_token(parent),
        change=link,
        capabilities=capabilities,
        submission="graph-link",
    )
    replay = await _graph_call(
        writer,
        parent=parent_identity,
        scalar_token="ignored-on-completed-replay",
        change=link,
        capabilities=capabilities,
        submission="graph-link",
    )
    assert not first.replayed and replay.replayed
    assert replay.relationship_results[0].added_target_identities == (_identity(1),)

    async with session_factory() as session:
        parent = (await session.scalars(select(Parent))).one()
        await session.refresh(parent, attribute_names=["children"])
        assert [child.id for child in parent.children] == [1]
        unlink_token = writer.issue_update_token(parent)
    unlink = RelationshipChangePlan(
        operation_id="graph:parents:children:unlink",
        relationship_id="children",
        steps=(UnlinkRelated(identity=_identity(1)),),
        authorization_requirement=PermissionRequirement.all_of("admin.resources.parents.update"),
        concurrency_token=await relationships.issue_concurrency_token(parent_identity, "children"),
    )
    await _graph_call(
        writer,
        parent=parent_identity,
        scalar_token=unlink_token,
        change=unlink,
        capabilities=_capabilities(parent_identity, unlink),
        submission="graph-unlink",
    )
    async with session_factory() as session:
        child = (await session.scalars(select(Child))).one()
    assert child.parent_id is None
