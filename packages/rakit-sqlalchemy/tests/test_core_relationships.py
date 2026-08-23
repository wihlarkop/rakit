from __future__ import annotations

import pytest
from rakit_core.concurrency import ConcurrencyTokenService
from rakit_core.config import SecretValue
from rakit_core.crypto import TokenService
from rakit_core.definitions import ResourceFieldPolicy
from rakit_core.errors import ErrorCode, RakitError
from rakit_core.identity import RecordIdentity
from rakit_core.permissions import PermissionRequirement
from rakit_core.relationship_mutations import (
    ClearRelated,
    LinkRelated,
    RelationshipChangePlan,
    ReorderRelated,
    SetRelated,
    UnlinkRelated,
    UpdateAssociationRelated,
)
from rakit_core.relationships import (
    CompiledRelationship,
    RelationshipCardinality,
    RelationshipDefinition,
    RelationshipEditMode,
    RelationshipKind,
    RelationshipOrderingDefinition,
)
from rakit_core.transactions import TransactionPolicy
from rakit_sqlalchemy.core_concurrency import MappingVersionProvider
from rakit_sqlalchemy.core_datasource import SQLAlchemyCoreDataSource
from rakit_sqlalchemy.core_relationship_mutations import SQLAlchemyCoreRelationshipMutationService
from rakit_sqlalchemy.core_relationships import SQLAlchemyCoreRelationshipBinding
from rakit_sqlalchemy.core_uow import SQLAlchemyCoreUnitOfWork
from sqlalchemy import Column, ForeignKey, Integer, MetaData, String, Table, select
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine


REQUIREMENT = PermissionRequirement.all_of("admin.resources.orders.update")


def _identity(value: int) -> RecordIdentity:
    return RecordIdentity(values={"id": value})


def _tokens() -> ConcurrencyTokenService:
    return ConcurrencyTokenService(
        TokenService.single_key(
            key_id="test",
            value=SecretValue("core-relationship-concurrency-secret"),
            admin_id="test",
        )
    )


def _source(
    table: Table,
    engine: AsyncEngine,
    *,
    bindings: dict[str, SQLAlchemyCoreRelationshipBinding] | None = None,
) -> SQLAlchemyCoreDataSource:
    fields = tuple(column.key for column in table.columns)
    return SQLAlchemyCoreDataSource(
        table=table,
        engine=engine,
        field_policy=ResourceFieldPolicy(list_fields=fields, detail_fields=fields),
        relationship_bindings=bindings,
    )


def _compiled(definition: RelationshipDefinition) -> CompiledRelationship:
    return CompiledRelationship(
        source_resource_id="orders",
        definition=definition,
        mutation_permission=REQUIREMENT,
        target_delete_permission=None,
        route_path=f"/orders/{{identity}}/_relationships/{definition.relationship_id}",
        ordering=definition.ordering,
    )


def _change(
    relationship_id: str,
    token: str,
    *steps,
) -> RelationshipChangePlan:
    return RelationshipChangePlan(
        operation_id=f"relationship:orders:{relationship_id}:update",
        relationship_id=relationship_id,
        steps=steps,
        authorization_requirement=REQUIREMENT,
        concurrency_token=token,
    )


async def _execute(
    engine: AsyncEngine,
    service: SQLAlchemyCoreRelationshipMutationService,
    parent_identity: RecordIdentity,
    change: RelationshipChangePlan,
):
    async with SQLAlchemyCoreUnitOfWork(engine, policy=TransactionPolicy.AUTO) as uow:
        result = await service.execute_in_uow(
            uow,
            parent_identity=parent_identity,
            change=change,
        )
        await uow.mark_success()
        return result


def test_core_relationship_resolution_is_explicit_and_fails_closed_on_ambiguity() -> None:
    metadata = MetaData()
    customers = Table(
        "core_resolution_customers",
        metadata,
        Column("id", Integer, primary_key=True),
        Column("name", String(100), nullable=False),
    )
    orders = Table(
        "core_resolution_orders",
        metadata,
        Column("id", Integer, primary_key=True),
        Column("customer_id", ForeignKey(customers.c.id), nullable=True),
    )
    ambiguous = Table(
        "core_resolution_ambiguous_orders",
        metadata,
        Column("id", Integer, primary_key=True),
        Column("billing_customer_id", ForeignKey(customers.c.id), nullable=True),
        Column("shipping_customer_id", ForeignKey(customers.c.id), nullable=True),
    )
    profiles = Table(
        "core_resolution_profiles",
        metadata,
        Column("id", Integer, primary_key=True),
        Column("order_id", ForeignKey(orders.c.id), unique=True, nullable=True),
    )
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    customer_source = _source(customers, engine)

    customer_definition = RelationshipDefinition(
        relationship_id="customer",
        target_resource_id="customers",
        label="Customer",
        kind=RelationshipKind.MANY_TO_ONE,
        cardinality=RelationshipCardinality.TO_ONE,
        nullable=True,
        edit_mode=RelationshipEditMode.LINK,
        writable=True,
        record_label_field="name",
    )
    order_source = _source(orders, engine)
    order_source.validate_relationship(customer_definition, customer_source)
    resolved = order_source.resolved_relationship("customer")
    assert resolved.foreign_key_field == "customer_id"
    assert resolved.foreign_key_on_source is True
    assert order_source.relationship_metadata["customer"].kind is RelationshipKind.MANY_TO_ONE

    ambiguous_source = _source(ambiguous, engine)
    with pytest.raises(RakitError) as raised:
        ambiguous_source.validate_relationship(customer_definition, customer_source)
    assert raised.value.details["reason"] == "foreign_key_path_ambiguous"

    explicit_source = _source(
        ambiguous,
        engine,
        bindings={
            "customer": SQLAlchemyCoreRelationshipBinding(
                foreign_key_field="shipping_customer_id"
            )
        },
    )
    explicit_source.validate_relationship(customer_definition, customer_source)
    assert explicit_source.resolved_relationship("customer").foreign_key_field == (
        "shipping_customer_id"
    )

    profile_definition = RelationshipDefinition(
        relationship_id="profile",
        target_resource_id="profiles",
        label="Profile",
        kind=RelationshipKind.ONE_TO_ONE,
        cardinality=RelationshipCardinality.TO_ONE,
        nullable=True,
        edit_mode=RelationshipEditMode.LINK,
        writable=True,
    )
    order_source.validate_relationship(profile_definition, _source(profiles, engine))
    profile_resolution = order_source.resolved_relationship("profile")
    assert profile_resolution.foreign_key_field == "order_id"
    assert profile_resolution.foreign_key_on_source is False


@pytest.mark.anyio
async def test_core_many_to_one_set_clear_and_stale_relationship_token() -> None:
    metadata = MetaData()
    customers = Table(
        "core_to_one_customers",
        metadata,
        Column("id", Integer, primary_key=True),
        Column("name", String(100), nullable=False),
    )
    orders = Table(
        "core_to_one_orders",
        metadata,
        Column("id", Integer, primary_key=True),
        Column("version", Integer, nullable=False),
        Column("customer_id", ForeignKey(customers.c.id), nullable=True),
    )
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    parent_source = _source(orders, engine)
    customer_source = _source(customers, engine)
    definition = RelationshipDefinition(
        relationship_id="customer",
        target_resource_id="customers",
        label="Customer",
        kind=RelationshipKind.MANY_TO_ONE,
        cardinality=RelationshipCardinality.TO_ONE,
        nullable=True,
        edit_mode=RelationshipEditMode.LINK,
        writable=True,
        record_label_field="name",
    )
    parent_source.validate_relationship(definition, customer_source)
    service = SQLAlchemyCoreRelationshipMutationService(
        parent_data_source=parent_source,
        relationships=(_compiled(definition),),
        target_data_sources={"customers": customer_source},
        concurrency_provider=MappingVersionProvider("version"),
        concurrency_tokens=_tokens(),
    )
    parent = _identity(1)
    try:
        async with engine.begin() as connection:
            await connection.run_sync(metadata.create_all)
            await connection.execute(
                customers.insert(),
                (
                    {"id": 1, "name": "Ada"},
                    {"id": 2, "name": "Grace"},
                ),
            )
            await connection.execute(
                orders.insert().values(id=1, version=1, customer_id=1)
            )

        page = await service.editor_page(parent, "customer", page=1, per_page=1)
        assert [row.candidate.label for row in page.items] == ["Ada"]
        assert page.has_next is False

        stale_token = await service.issue_concurrency_token(parent, "customer")
        changed = await _execute(
            engine,
            service,
            parent,
            _change("customer", stale_token, SetRelated(identity=_identity(2))),
        )
        assert changed.target_identities == (_identity(2),)
        assert changed.added_target_identities == (_identity(2),)
        assert changed.removed_target_identities == (_identity(1),)

        with pytest.raises(RakitError) as stale:
            await _execute(
                engine,
                service,
                parent,
                _change("customer", stale_token, SetRelated(identity=_identity(1))),
            )
        assert stale.value.code is ErrorCode.RESOURCE_CONFLICT

        fresh_token = await service.issue_concurrency_token(parent, "customer")
        cleared = await _execute(
            engine,
            service,
            parent,
            _change("customer", fresh_token, ClearRelated()),
        )
        assert cleared.target_identities == ()
        assert cleared.removed_target_identities == (_identity(2),)

        async with engine.connect() as connection:
            row = (await connection.execute(select(orders))).mappings().one()
        assert row["customer_id"] is None
        assert row["version"] == 3
    finally:
        await engine.dispose()


@pytest.mark.anyio
async def test_core_one_to_many_link_unlink_reorder_and_editor_page() -> None:
    metadata = MetaData()
    orders = Table(
        "core_o2m_orders",
        metadata,
        Column("id", Integer, primary_key=True),
        Column("version", Integer, nullable=False),
    )
    items = Table(
        "core_o2m_items",
        metadata,
        Column("id", Integer, primary_key=True),
        Column("name", String(100), nullable=False),
        Column("order_id", ForeignKey(orders.c.id), nullable=True),
        Column("position", Integer, nullable=False),
    )
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    parent_source = _source(orders, engine)
    item_source = _source(items, engine)
    ordering = RelationshipOrderingDefinition(position_field="position")
    definition = RelationshipDefinition(
        relationship_id="items",
        target_resource_id="items",
        label="Items",
        kind=RelationshipKind.ONE_TO_MANY,
        cardinality=RelationshipCardinality.TO_MANY,
        nullable=True,
        ordered=True,
        ordering=ordering,
        edit_mode=RelationshipEditMode.LINK,
        writable=True,
        record_label_field="name",
    )
    parent_source.validate_relationship(definition, item_source)
    service = SQLAlchemyCoreRelationshipMutationService(
        parent_data_source=parent_source,
        relationships=(_compiled(definition),),
        target_data_sources={"items": item_source},
        concurrency_provider=MappingVersionProvider("version"),
        concurrency_tokens=_tokens(),
    )
    parent = _identity(1)
    try:
        async with engine.begin() as connection:
            await connection.run_sync(metadata.create_all)
            await connection.execute(orders.insert().values(id=1, version=1))
            await connection.execute(
                items.insert(),
                (
                    {"id": 1, "name": "first", "order_id": 1, "position": 0},
                    {"id": 2, "name": "second", "order_id": None, "position": 1},
                    {"id": 3, "name": "third", "order_id": 1, "position": 2},
                ),
            )

        token = await service.issue_concurrency_token(parent, "items")
        linked = await _execute(
            engine,
            service,
            parent,
            _change("items", token, LinkRelated(identity=_identity(2))),
        )
        assert set(linked.target_identities) == {_identity(1), _identity(2), _identity(3)}
        assert linked.added_target_identities == (_identity(2),)

        token = await service.issue_concurrency_token(parent, "items")
        await _execute(
            engine,
            service,
            parent,
            _change(
                "items",
                token,
                ReorderRelated(identities=(_identity(3), _identity(2), _identity(1))),
            ),
        )
        assert await service.reorder_identities(parent, "items", maximum=3) == (
            _identity(3),
            _identity(2),
            _identity(1),
        )
        assert await service.reorder_identities(parent, "items", maximum=2) is None

        page = await service.editor_page(
            parent,
            "items",
            child_fields=("name", "position"),
            page=1,
            per_page=2,
        )
        assert len(page.items) == 2
        assert page.has_next is True
        assert all("position" in row.values for row in page.items)

        token = await service.issue_concurrency_token(parent, "items")
        unlinked = await _execute(
            engine,
            service,
            parent,
            _change("items", token, UnlinkRelated(identity=_identity(2))),
        )
        assert _identity(2) in unlinked.removed_target_identities

        async with engine.connect() as connection:
            item_two = (
                await connection.execute(select(items).where(items.c.id == 2))
            ).mappings().one()
        assert item_two["order_id"] is None
    finally:
        await engine.dispose()


@pytest.mark.anyio
async def test_core_many_to_many_link_and_unlink_preserve_target_rows() -> None:
    metadata = MetaData()
    orders = Table(
        "core_m2m_orders",
        metadata,
        Column("id", Integer, primary_key=True),
        Column("version", Integer, nullable=False),
    )
    tags = Table(
        "core_m2m_tags",
        metadata,
        Column("id", Integer, primary_key=True),
        Column("name", String(100), nullable=False),
    )
    order_tags = Table(
        "core_m2m_order_tags",
        metadata,
        Column("order_id", ForeignKey(orders.c.id), primary_key=True),
        Column("tag_id", ForeignKey(tags.c.id), primary_key=True),
    )
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    parent_source = _source(orders, engine)
    tag_source = _source(tags, engine)
    definition = RelationshipDefinition(
        relationship_id="tags",
        target_resource_id="tags",
        label="Tags",
        kind=RelationshipKind.MANY_TO_MANY,
        cardinality=RelationshipCardinality.TO_MANY,
        nullable=True,
        edit_mode=RelationshipEditMode.LINK,
        writable=True,
        record_label_field="name",
    )
    parent_source.validate_relationship(definition, tag_source)
    resolved = parent_source.resolved_relationship("tags")
    assert resolved.secondary_table is order_tags
    service = SQLAlchemyCoreRelationshipMutationService(
        parent_data_source=parent_source,
        relationships=(_compiled(definition),),
        target_data_sources={"tags": tag_source},
        concurrency_provider=MappingVersionProvider("version"),
        concurrency_tokens=_tokens(),
    )
    parent = _identity(1)
    try:
        async with engine.begin() as connection:
            await connection.run_sync(metadata.create_all)
            await connection.execute(orders.insert().values(id=1, version=1))
            await connection.execute(
                tags.insert(),
                ({"id": 1, "name": "first"}, {"id": 2, "name": "second"}),
            )
            await connection.execute(order_tags.insert().values(order_id=1, tag_id=1))

        token = await service.issue_concurrency_token(parent, "tags")
        linked = await _execute(
            engine,
            service,
            parent,
            _change("tags", token, LinkRelated(identity=_identity(2))),
        )
        assert set(linked.target_identities) == {_identity(1), _identity(2)}

        token = await service.issue_concurrency_token(parent, "tags")
        removed = await _execute(
            engine,
            service,
            parent,
            _change("tags", token, UnlinkRelated(identity=_identity(1))),
        )
        assert removed.target_identities == (_identity(2),)

        async with engine.connect() as connection:
            tag_names = tuple(
                (await connection.execute(select(tags.c.name).order_by(tags.c.id))).scalars()
            )
            bridges = tuple(
                (await connection.execute(select(order_tags.c.tag_id))).scalars()
            )
        assert tag_names == ("first", "second")
        assert bridges == (2,)
    finally:
        await engine.dispose()


@pytest.mark.anyio
async def test_core_association_object_updates_scalars_and_order_inside_root_uow() -> None:
    metadata = MetaData()
    orders = Table(
        "core_assoc_orders",
        metadata,
        Column("id", Integer, primary_key=True),
        Column("version", Integer, nullable=False),
    )
    tags = Table(
        "core_assoc_tags",
        metadata,
        Column("id", Integer, primary_key=True),
        Column("name", String(100), nullable=False),
    )
    memberships = Table(
        "core_assoc_memberships",
        metadata,
        Column("id", Integer, primary_key=True),
        Column("order_id", ForeignKey(orders.c.id), nullable=False),
        Column("tag_id", ForeignKey(tags.c.id), nullable=False),
        Column("role", String(50), nullable=False),
        Column("position", Integer, nullable=False),
    )
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    parent_source = _source(orders, engine)
    membership_source = _source(memberships, engine)
    tag_source = _source(tags, engine)
    ordering = RelationshipOrderingDefinition(position_field="position")
    definition = RelationshipDefinition(
        relationship_id="memberships",
        target_resource_id="memberships",
        association_target_resource_id="tags",
        label="Memberships",
        kind=RelationshipKind.ASSOCIATION_OBJECT,
        cardinality=RelationshipCardinality.TO_MANY,
        nullable=True,
        ordered=True,
        ordering=ordering,
        edit_mode=RelationshipEditMode.INLINE,
        writable=True,
        association_fields=("role", "position"),
        record_label_field="name",
    )
    parent_source.validate_relationship(definition, membership_source, tag_source)
    service = SQLAlchemyCoreRelationshipMutationService(
        parent_data_source=parent_source,
        relationships=(_compiled(definition),),
        target_data_sources={"memberships": membership_source, "tags": tag_source},
        concurrency_provider=MappingVersionProvider("version"),
        concurrency_tokens=_tokens(),
    )
    parent = _identity(1)
    try:
        async with engine.begin() as connection:
            await connection.run_sync(metadata.create_all)
            await connection.execute(orders.insert().values(id=1, version=1))
            await connection.execute(
                tags.insert(),
                ({"id": 1, "name": "first"}, {"id": 2, "name": "second"}),
            )
            await connection.execute(
                memberships.insert(),
                (
                    {"id": 10, "order_id": 1, "tag_id": 1, "role": "reader", "position": 0},
                    {"id": 11, "order_id": 1, "tag_id": 2, "role": "writer", "position": 1},
                ),
            )

        page = await service.editor_page(
            parent,
            "memberships",
            page=1,
            per_page=10,
        )
        assert [row.candidate.label for row in page.items] == ["first", "second"]
        assert [row.association_identity for row in page.items] == [_identity(10), _identity(11)]
        assert page.items[0].values["role"] == "reader"

        token = await service.issue_concurrency_token(parent, "memberships")
        updated = await _execute(
            engine,
            service,
            parent,
            _change(
                "memberships",
                token,
                UpdateAssociationRelated(
                    target_identity=_identity(1),
                    association_identity=_identity(10),
                    values={"role": "owner"},
                ),
            ),
        )
        assert updated.target_identities == (_identity(1), _identity(2))

        token = await service.issue_concurrency_token(parent, "memberships")
        await _execute(
            engine,
            service,
            parent,
            _change(
                "memberships",
                token,
                ReorderRelated(identities=(_identity(2), _identity(1))),
            ),
        )
        assert await service.reorder_identities(parent, "memberships", maximum=2) == (
            _identity(2),
            _identity(1),
        )

        async with engine.connect() as connection:
            rows = (
                await connection.execute(select(memberships).order_by(memberships.c.id))
            ).mappings().all()
        assert rows[0]["role"] == "owner"
        assert [row["position"] for row in rows] == [1, 0]
    finally:
        await engine.dispose()
