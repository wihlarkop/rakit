from collections.abc import AsyncIterator

import pytest
from rakit_core.auth import Principal
from rakit_core.concurrency import AttributeVersionProvider
from rakit_core.config import SecretValue
from rakit_core.crypto import TokenService
from rakit_core.definitions import ResourceFieldPolicy
from rakit_core.errors import ErrorCode, RakitError
from rakit_core.fields import FieldDefinition
from rakit_core.forms import FormSchema
from rakit_core.idempotency import OperationReceipt
from rakit_core.identity import RecordIdentity
from rakit_core.mutations import OperationAuthorization, OperationAuthorizationSet
from rakit_core.operations import CancellationContext, OperationContext, activate_operation_context
from rakit_core.permissions import PermissionRequirement
from rakit_core.relationship_mutations import (
    CreateRelated,
    DeleteRelated,
    LinkRelated,
    RelationshipChangePlan,
    ReorderRelated,
    UnlinkRelated,
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


class Parent(Base):
    __tablename__ = "graph_mutation_parents"

    id: Mapped[int] = mapped_column(primary_key=True)
    version: Mapped[int] = mapped_column(default=1)
    name: Mapped[str]
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
        form_schema=FormSchema(fields=(FieldDefinition(field_id="name", python_type=str),)),
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


async def _graph_call(
    writer: SQLAlchemyMutationService,
    *,
    parent: RecordIdentity,
    scalar_token: str,
    change: RelationshipChangePlan,
    capabilities: OperationAuthorizationSet,
    submission: str,
    name: str = "changed",
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

    writer, child_writer, relationships = _services(session_factory, allow_child_delete=True)
    parent_identity = _identity(parent.id)
    delete_token = await child_writer.issue_delete_token(_identity(child.id))
    change = RelationshipChangePlan(
        operation_id="graph:parents:children:delete",
        relationship_id="children",
        steps=(
            DeleteRelated(
                identity=_identity(child.id),
                concurrency_token=child_writer.issue_update_token(child),
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

    await _graph_call(
        writer,
        parent=parent_identity,
        scalar_token=writer.issue_update_token(parent),
        change=change,
        capabilities=_capabilities(
            parent_identity,
            change,
            child_operation="target-delete",
            child_identity=_identity(child.id),
        ),
        submission="graph-delete",
    )
    async with session_factory() as session:
        assert list((await session.scalars(select(Child))).all()) == []


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
