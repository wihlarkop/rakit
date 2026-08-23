from __future__ import annotations

import asyncio
from collections.abc import Mapping

from rakit_core.adapter_capabilities import (
    CONCURRENCY_ATOMIC_OPTIMISTIC,
    PERSISTENCE_READ,
    PERSISTENCE_RELATIONSHIPS,
    PERSISTENCE_WRITE,
    TRANSACTIONS_ROOT_UOW,
)
from rakit_core.compiler import ApplicationBuilder
from rakit_core.concurrency import ConcurrencyTokenService
from rakit_core.config import SecretValue
from rakit_core.conformance import conformance_matrix_rows, run_integration_conformance
from rakit_core.crypto import TokenService
from rakit_core.definitions import ResourceFieldPolicy
from rakit_core.errors import ErrorCode, RakitError
from rakit_core.generated_input import GeneratedInput
from rakit_core.generated_operations import GeneratedCrudRequest
from rakit_core.generated_runtime import GeneratedResourceExecutorContext
from rakit_core.identity import RecordIdentity
from rakit_core.operations import CancellationContext, OperationContext
from rakit_core.permissions import PermissionRequirement
from rakit_core.relationship_mutations import RelationshipChangePlan, SetRelated
from rakit_core.relationships import (
    CompiledRelationship,
    RelationshipCardinality,
    RelationshipDefinition,
    RelationshipEditMode,
    RelationshipKind,
)
from rakit_core.testing import DataSourceContractSuite
from rakit_core.testing.capability_conformance import CANONICAL_CONFORMANCE_SPEC_REGISTRY
from rakit_core.transactions import TransactionPolicy
from rakit_sqlalchemy.core_concurrency import MappingVersionProvider
from rakit_sqlalchemy.core_datasource import SQLAlchemyCoreDataSource
from rakit_sqlalchemy.core_generated import (
    SQLAlchemyCoreGeneratedResourceExecutor,
    SQLAlchemyCoreGeneratedResourceExecutorProvider,
)
from rakit_sqlalchemy.core_plugin import SQLAlchemyCorePlugin
from rakit_sqlalchemy.core_relationship_mutations import SQLAlchemyCoreRelationshipMutationService
from rakit_sqlalchemy.core_uow import SQLAlchemyCoreOperationUnitOfWorkFactory
from rakit_sqlalchemy.discovery import SQLALCHEMY_CORE_INTEGRATION
from sqlalchemy import Column, ForeignKey, Integer, MetaData, String, Table, delete, select
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

metadata = MetaData()
items = Table(
    "core_conformance_items",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("name", String(100), nullable=False),
    Column("group", String(100), nullable=False),
    Column("score", Integer, nullable=False),
)
atomic_items = Table(
    "core_conformance_atomic_items",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("name", String(100), nullable=False),
    Column("version", Integer, nullable=False),
)
customers = Table(
    "core_conformance_customers",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("name", String(100), nullable=False),
)
orders = Table(
    "core_conformance_orders",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("version", Integer, nullable=False),
    Column("customer_id", ForeignKey(customers.c.id), nullable=True),
)

FIXTURE: tuple[Mapping[str, object], ...] = (
    {"id": 1, "name": "Ada", "group": "engineering", "score": 10},
    {"id": 2, "name": "Grace", "group": "engineering", "score": 20},
    {"id": 3, "name": "Alan", "group": "science", "score": 30},
    {"id": 4, "name": "Linus", "group": "science", "score": 40},
    {"id": 5, "name": "Mary", "group": "operations", "score": 50},
    {"id": 6, "name": "Katherine", "group": "engineering", "score": 60},
    {"id": 7, "name": "Dorothy", "group": "operations", "score": 70},
)

POLICY = ResourceFieldPolicy(
    list_fields=("id", "name", "group", "score"),
    detail_fields=("id", "name", "group", "score"),
    filter_fields=("group", "score"),
    search_fields=("name",),
    sort_fields=("name", "group", "score"),
)
ATOMIC_POLICY = ResourceFieldPolicy(
    list_fields=("id", "name", "version"),
    detail_fields=("id", "name", "version"),
)
RELATIONSHIP_REQUIREMENT = PermissionRequirement.all_of("admin.resources.orders.update")


class CoreReadContract(DataSourceContractSuite):
    field_policy = POLICY
    identity_fields = ("id",)
    sort_group_field = "group"

    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    async def make_datasource(self) -> SQLAlchemyCoreDataSource:
        return SQLAlchemyCoreDataSource(
            table=items,
            engine=self._engine,
            field_policy=self.field_policy,
        )

    async def fixture_records(self) -> tuple[Mapping[str, object], ...]:
        return FIXTURE


class CorePersistenceConformanceHarness:
    def __init__(self, engine: AsyncEngine) -> None:
        self.engine = engine
        builder = ApplicationBuilder()
        plugin = SQLAlchemyCorePlugin(engine=engine)
        builder.install(plugin)
        runtime = plugin._claim(items, POLICY)
        assert runtime is not None
        assert runtime.generated_executor_provider is not None
        executor = runtime.generated_executor_provider.build(
            GeneratedResourceExecutorContext(
                resource_id="items",
                data_source=runtime.data_source,
            )
        )
        assert isinstance(executor, SQLAlchemyCoreGeneratedResourceExecutor)
        factory = dict(builder.unit_of_work_factories)["persistence.sqlalchemy-core"]
        assert isinstance(factory, SQLAlchemyCoreOperationUnitOfWorkFactory)
        self.executor = executor
        self.factory = factory
        self.tokens = ConcurrencyTokenService(
            TokenService.single_key(
                key_id="test",
                value=SecretValue("core-conformance-concurrency-secret"),
                admin_id="test",
            )
        )

    async def _reset(self, records: tuple[Mapping[str, object], ...] = ()) -> None:
        async with self.engine.begin() as connection:
            await connection.execute(delete(items))
            if records:
                await connection.execute(items.insert(), [dict(record) for record in records])

    async def _execute(
        self,
        request: GeneratedCrudRequest,
        *,
        success: bool,
        executor: SQLAlchemyCoreGeneratedResourceExecutor | None = None,
        resource_id: str = "items",
    ):
        context = OperationContext(
            deadline=None,
            cancellation=CancellationContext(),
            resource_id=resource_id,
        )
        async with self.factory.open(
            policy=TransactionPolicy.AUTO,
            event_publisher=None,
            operation_context=context,
        ) as uow:
            object.__setattr__(context, "unit_of_work", uow)
            try:
                result = await (executor or self.executor).execute(context, request)
                if success:
                    await uow.mark_success()
                return result, context
            finally:
                object.__setattr__(context, "unit_of_work", None)

    async def _rows(self) -> tuple[dict[str, object], ...]:
        async with self.engine.connect() as connection:
            result = await connection.execute(select(items).order_by(items.c.id))
            return tuple(dict(row) for row in result.mappings().all())

    async def assert_read_semantics(self) -> None:
        await self._reset(FIXTURE)
        suite = CoreReadContract(self.engine)
        await suite.run_all()

    async def assert_write_semantics(self) -> None:
        await self._reset()
        created, _ = await self._execute(
            GeneratedCrudRequest.create(
                GeneratedInput(
                    values={"name": "Created", "group": "test", "score": 1},
                    present_fields=frozenset({"name", "group", "score"}),
                )
            ),
            success=True,
        )
        assert await self._rows() == (
            {
                "id": created.identity.values["id"],
                "name": "Created",
                "group": "test",
                "score": 1,
            },
        )

        updated, _ = await self._execute(
            GeneratedCrudRequest.update_partial(
                created.identity,
                GeneratedInput(
                    values={"score": 2},
                    present_fields=frozenset({"score"}),
                ),
            ),
            success=True,
        )
        assert updated.record == {
            "id": created.identity.values["id"],
            "name": "Created",
            "group": "test",
            "score": 2,
        }

        await self._execute(GeneratedCrudRequest.delete(created.identity), success=True)
        assert await self._rows() == ()

    async def assert_relationship_semantics(self) -> None:
        parent_source = SQLAlchemyCoreDataSource(
            table=orders,
            engine=self.engine,
            field_policy=ResourceFieldPolicy(
                list_fields=("id", "version", "customer_id"),
                detail_fields=("id", "version", "customer_id"),
            ),
        )
        target_source = SQLAlchemyCoreDataSource(
            table=customers,
            engine=self.engine,
            field_policy=ResourceFieldPolicy(
                list_fields=("id", "name"),
                detail_fields=("id", "name"),
            ),
        )
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
        parent_source.validate_relationship(definition, target_source)
        relationship = CompiledRelationship(
            source_resource_id="orders",
            definition=definition,
            mutation_permission=RELATIONSHIP_REQUIREMENT,
            target_delete_permission=None,
            route_path="/orders/{identity}/_relationships/customer",
        )
        service = SQLAlchemyCoreRelationshipMutationService(
            parent_data_source=parent_source,
            relationships=(relationship,),
            target_data_sources={"customers": target_source},
            concurrency_provider=MappingVersionProvider("version"),
            concurrency_tokens=self.tokens,
        )
        parent_identity = RecordIdentity(values={"id": 1})
        target_identity = RecordIdentity(values={"id": 2})
        async with self.engine.begin() as connection:
            await connection.execute(delete(orders))
            await connection.execute(delete(customers))
            await connection.execute(
                customers.insert(),
                ({"id": 1, "name": "Ada"}, {"id": 2, "name": "Grace"}),
            )
            await connection.execute(orders.insert().values(id=1, version=1, customer_id=1))

        token = await service.issue_concurrency_token(parent_identity, "customer")
        change = RelationshipChangePlan(
            operation_id="relationship:orders:customer:update",
            relationship_id="customer",
            steps=(SetRelated(identity=target_identity),),
            authorization_requirement=RELATIONSHIP_REQUIREMENT,
            concurrency_token=token,
        )
        context = OperationContext(
            deadline=None,
            cancellation=CancellationContext(),
            resource_id="orders",
        )
        async with self.factory.open(
            policy=TransactionPolicy.AUTO,
            event_publisher=None,
            operation_context=context,
        ) as uow:
            object.__setattr__(context, "unit_of_work", uow)
            try:
                result = await service.execute_in_uow(
                    uow,
                    parent_identity=parent_identity,
                    change=change,
                )
                await uow.mark_success()
            finally:
                object.__setattr__(context, "unit_of_work", None)
        assert result.target_identities == (target_identity,)
        assert result.added_target_identities == (target_identity,)
        async with self.engine.connect() as connection:
            row = (await connection.execute(select(orders))).mappings().one()
        assert row["customer_id"] == 2
        assert row["version"] == 2

    async def assert_root_uow_semantics(self) -> None:
        await self._reset()
        rolled_back, rollback_context = await self._execute(
            GeneratedCrudRequest.create(
                GeneratedInput(
                    values={"name": "Rollback", "group": "test", "score": 1},
                    present_fields=frozenset({"name", "group", "score"}),
                )
            ),
            success=False,
        )
        assert rolled_back.record is not None
        assert await self._rows() == ()
        assert rollback_context.durable_commit_completed is False

        committed, commit_context = await self._execute(
            GeneratedCrudRequest.create(
                GeneratedInput(
                    values={"name": "Commit", "group": "test", "score": 2},
                    present_fields=frozenset({"name", "group", "score"}),
                )
            ),
            success=True,
        )
        assert await self._rows() == (
            {
                "id": committed.identity.values["id"],
                "name": "Commit",
                "group": "test",
                "score": 2,
            },
        )
        assert commit_context.durable_commit_completed is True

    async def assert_atomic_optimistic_semantics(self) -> None:
        source = SQLAlchemyCoreDataSource(
            table=atomic_items,
            engine=self.engine,
            field_policy=ATOMIC_POLICY,
        )
        executor = SQLAlchemyCoreGeneratedResourceExecutorProvider(source).build(
            GeneratedResourceExecutorContext(
                resource_id="atomic-items",
                data_source=source,
                concurrency_provider=MappingVersionProvider("version"),
                concurrency_tokens=self.tokens,
            )
        )
        assert isinstance(executor, SQLAlchemyCoreGeneratedResourceExecutor)
        identity = RecordIdentity(values={"id": 1})
        async with self.engine.begin() as connection:
            await connection.execute(delete(atomic_items))
            await connection.execute(
                atomic_items.insert().values(id=1, name="before", version=1)
            )

        stale_token = self.tokens.issue("atomic-items", identity, 1)
        updated, _ = await self._execute(
            GeneratedCrudRequest.update_partial(
                identity,
                GeneratedInput(
                    values={"name": "after"},
                    present_fields=frozenset({"name"}),
                ),
                concurrency_token=stale_token,
            ),
            success=True,
            executor=executor,
            resource_id="atomic-items",
        )
        assert updated.record == {"id": 1, "name": "after", "version": 2}

        try:
            await self._execute(
                GeneratedCrudRequest.update_partial(
                    identity,
                    GeneratedInput(
                        values={"name": "stale"},
                        present_fields=frozenset({"name"}),
                    ),
                    concurrency_token=stale_token,
                ),
                success=True,
                executor=executor,
                resource_id="atomic-items",
            )
        except RakitError as exc:
            assert exc.code == ErrorCode.RESOURCE_CONFLICT
            assert exc.status_code == 409
        else:
            raise AssertionError("stale Core optimistic update must fail")

        async with self.engine.connect() as connection:
            row = (await connection.execute(select(atomic_items))).mappings().one()
        assert dict(row) == {"id": 1, "name": "after", "version": 2}


def test_sqlalchemy_core_conforms_to_every_advertised_v1_capability() -> None:
    async def scenario() -> None:
        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        try:
            async with engine.begin() as connection:
                await connection.run_sync(metadata.create_all)

            harness = CorePersistenceConformanceHarness(engine)
            harnesses = {
                PERSISTENCE_READ.name: harness,
                PERSISTENCE_WRITE.name: harness,
                PERSISTENCE_RELATIONSHIPS.name: harness,
                TRANSACTIONS_ROOT_UOW.name: harness,
                CONCURRENCY_ATOMIC_OPTIMISTIC.name: harness,
            }
            result = await run_integration_conformance(
                descriptor=SQLALCHEMY_CORE_INTEGRATION,
                harnesses=harnesses,
                specs=CANONICAL_CONFORMANCE_SPEC_REGISTRY,
            )

            assert SQLALCHEMY_CORE_INTEGRATION.advertised_capabilities.names == (
                "persistence.read",
                "persistence.write",
                "persistence.relationships",
                "transactions.root-uow",
                "concurrency.atomic-optimistic",
            )
            assert result.passed, result.failures
            rows = conformance_matrix_rows((result,))
            assert len(rows) == 5
            assert all(row.contract_version == 1 and row.passed for row in rows)
        finally:
            await engine.dispose()

    asyncio.run(scenario())