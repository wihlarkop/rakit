from __future__ import annotations

import asyncio
from collections.abc import Mapping

from pydantic import BaseModel
from rakit_core.adapter_capabilities import (
    CONCURRENCY_ATOMIC_OPTIMISTIC,
    PERSISTENCE_READ,
    PERSISTENCE_RELATIONSHIPS,
    PERSISTENCE_WRITE,
    SCHEMA_FIELD_INTROSPECTION,
    SCHEMA_INPUT_VALIDATION,
    SCHEMA_OUTPUT_SERIALIZATION,
    SCHEMA_PARTIAL_UPDATE,
    TRANSACTIONS_ROOT_UOW,
    WEB_ASGI,
    WEB_HTTP_ROUTING,
    WEB_STREAMING_RESPONSE,
)
from rakit_core.concurrency import AttributeVersionProvider, ConcurrencyTokenService
from rakit_core.config import SecretValue
from rakit_core.conformance import conformance_matrix_rows, run_integration_conformance
from rakit_core.crypto import TokenService
from rakit_core.definitions import ResourceFieldPolicy
from rakit_core.errors import ErrorCode, RakitError
from rakit_core.generated_api import ApiExposure, CompiledResourceApi, ResourceApiDefinition
from rakit_core.generated_input import GeneratedInput
from rakit_core.generated_operations import (
    GeneratedCrudRequest,
    GeneratedMutationResult,
    build_generated_operation_plan,
)
from rakit_core.generated_runtime import GeneratedResourceExecutorContext
from rakit_core.identity import RecordIdentity
from rakit_core.mutations import OperationAuthorization
from rakit_core.operations import (
    CancellationContext,
    OperationContext,
    activate_operation_context,
    new_operation_id,
    run_operation_plan,
)
from rakit_core.permissions import PermissionRequirement
from rakit_core.testing.capability_conformance import (
    CANONICAL_CONFORMANCE_SPEC_REGISTRY,
    PersistenceConformanceHarness,
    SchemaConformanceHarness,
    WebConformanceHarness,
)
from rakit_core.testing.datasource_contract import DataSourceContractSuite
from rakit_sqlalchemy.datasource import SQLAlchemyDataSource
from rakit_sqlalchemy.discovery import SQLALCHEMY_INTEGRATION
from rakit_sqlalchemy.generated import SQLAlchemyGeneratedResourceExecutorProvider
from rakit_sqlalchemy.uow import SQLAlchemyOperationUnitOfWorkFactory, SQLAlchemyUnitOfWork
from rakit_web.discovery import PYDANTIC_INTEGRATION, STARLETTE_INTEGRATION
from rakit_web.schema import PydanticSchemaAdapter
from sqlalchemy import ForeignKey, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from starlette.applications import Starlette
from starlette.responses import PlainTextResponse, StreamingResponse
from starlette.routing import Route


class Base(DeclarativeBase):
    pass


class ContractUser(Base):
    __tablename__ = "d1_contract_users"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str]
    name: Mapped[str]
    group: Mapped[str]
    score: Mapped[int]
    version: Mapped[int] = mapped_column(default=1)


class Parent(Base):
    __tablename__ = "d1_contract_parents"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str]
    children: Mapped[list[Child]] = relationship(back_populates="parent")


class Child(Base):
    __tablename__ = "d1_contract_children"

    id: Mapped[int] = mapped_column(primary_key=True)
    parent_id: Mapped[int] = mapped_column(ForeignKey("d1_contract_parents.id"))
    name: Mapped[str]
    parent: Mapped[Parent] = relationship(back_populates="children")


READ_FIXTURE: tuple[Mapping[str, object], ...] = (
    {
        "id": 1,
        "email": "ada@example.com",
        "name": "Ada Lovelace",
        "group": "engineering",
        "score": 10,
        "version": 1,
    },
    {
        "id": 2,
        "email": "grace@example.com",
        "name": "Grace Hopper",
        "group": "engineering",
        "score": 20,
        "version": 1,
    },
    {
        "id": 3,
        "email": "alan@example.com",
        "name": "Alan Turing",
        "group": "science",
        "score": 30,
        "version": 1,
    },
    {
        "id": 4,
        "email": "linus@example.com",
        "name": "Linus Torvalds",
        "group": "science",
        "score": 40,
        "version": 1,
    },
    {
        "id": 5,
        "email": "mary@example.com",
        "name": "Mary Jackson",
        "group": "operations",
        "score": 50,
        "version": 1,
    },
    {
        "id": 6,
        "email": "katherine@example.com",
        "name": "Katherine Johnson",
        "group": "engineering",
        "score": 60,
        "version": 1,
    },
    {
        "id": 7,
        "email": "dorothy@example.com",
        "name": "Dorothy Vaughan",
        "group": "operations",
        "score": 70,
        "version": 1,
    },
)


class SQLAlchemyReadContract(DataSourceContractSuite):
    field_policy = ResourceFieldPolicy(
        list_fields=("id", "email", "name", "group", "score", "version"),
        detail_fields=("id", "email", "name", "group", "score", "version"),
        filter_fields=("email", "group", "score"),
        search_fields=("email", "name"),
        sort_fields=("email", "name", "group", "score"),
    )
    identity_fields = ("id",)
    sort_group_field = "group"

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def make_datasource(self) -> SQLAlchemyDataSource:
        return SQLAlchemyDataSource(
            model=ContractUser,
            session_factory=self._session_factory,
            field_policy=self.field_policy,
        )

    async def fixture_records(self) -> tuple[Mapping[str, object], ...]:
        return READ_FIXTURE


class SQLAlchemyConformanceHarness(PersistenceConformanceHarness):
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self.session_factory = session_factory
        self.read_suite = SQLAlchemyReadContract(session_factory)
        self.data_source = SQLAlchemyDataSource(
            model=ContractUser,
            session_factory=session_factory,
            field_policy=SQLAlchemyReadContract.field_policy,
        )
        self.version_provider = AttributeVersionProvider("version")
        self.tokens = _tokens()
        self.executor = SQLAlchemyGeneratedResourceExecutorProvider(model=ContractUser).build(
            GeneratedResourceExecutorContext(
                resource_id="users",
                data_source=self.data_source,
                concurrency_provider=self.version_provider,
                concurrency_tokens=self.tokens,
            )
        )
        self.api = _api(self.data_source)
        self.uow_factory = SQLAlchemyOperationUnitOfWorkFactory(session_factory)

    async def assert_read_semantics(self) -> None:
        suite = self.read_suite
        await suite.assert_list_detail_and_not_found()
        await suite.assert_identity_round_trip()
        await suite.assert_filtering()
        await suite.assert_search()
        await suite.assert_deterministic_sorting()
        await suite.assert_identity_tie_breaker()
        await suite.assert_pagination()
        await suite.assert_stable_pagination()
        await suite.assert_count_policy_semantics()
        await suite.assert_error_translation()

    async def assert_write_semantics(self) -> None:
        created = await self._create("write@example.com")
        updated = await self._update(created, "write-updated@example.com")
        assert updated.record is not None
        assert updated.record.email == "write-updated@example.com"
        await self._delete(updated)
        async with self.session_factory() as session:
            assert await session.get(ContractUser, int(updated.identity.values["id"])) is None

    async def assert_relationship_semantics(self) -> None:
        data_source = SQLAlchemyDataSource(
            model=Parent,
            session_factory=self.session_factory,
            field_policy=ResourceFieldPolicy(
                list_fields=("id", "name"),
                detail_fields=("id", "name"),
            ),
        )
        metadata = data_source.relationship_metadata
        assert metadata, "relationship-capable model must expose relationship metadata"
        assert "children" in metadata
        assert metadata["children"].relationship_id == "children"

    async def assert_root_uow_semantics(self) -> None:
        async with SQLAlchemyUnitOfWork(self.session_factory) as uow:
            uow.session.add(ContractUser(email="uow@example.com", name="Uow", group="ops", score=90))
            await uow.mark_success()
        async with self.session_factory() as session:
            committed = await session.scalar(select(ContractUser).where(ContractUser.email == "uow@example.com"))
            assert committed is not None

        class RollbackProbe(Exception):
            pass

        try:
            async with SQLAlchemyUnitOfWork(self.session_factory) as uow:
                uow.session.add(
                    ContractUser(email="rollback@example.com", name="Rollback", group="ops", score=91)
                )
                await uow.session.flush()
                raise RollbackProbe
        except RollbackProbe:
            pass
        async with self.session_factory() as session:
            rolled_back = await session.scalar(
                select(ContractUser).where(ContractUser.email == "rollback@example.com")
            )
            assert rolled_back is None

    async def assert_atomic_optimistic_semantics(self) -> None:
        created = await self._create("concurrency@example.com")
        assert created.record is not None
        stale_token = self.tokens.issue(
            "users",
            created.identity,
            self.version_provider.version_for(created.record),
        )
        updated = await self._update(
            created,
            "concurrency-updated@example.com",
            concurrency_token=stale_token,
            concurrency_required=True,
        )
        assert updated.record is not None
        assert updated.record.version == 2
        try:
            await self._update(
                updated,
                "stale@example.com",
                concurrency_token=stale_token,
                concurrency_required=True,
            )
        except RakitError as exc:
            assert exc.code == ErrorCode.RESOURCE_CONFLICT
            assert exc.status_code == 409
        else:
            raise AssertionError("stale optimistic token must fail")
        async with self.session_factory() as session:
            current = await session.get(ContractUser, int(updated.identity.values["id"]))
            assert current is not None
            assert current.email == "concurrency-updated@example.com"
            assert current.version == 2

    async def _create(self, email: str) -> GeneratedMutationResult:
        return await _execute(
            api=self.api,
            executor=self.executor,
            request=GeneratedCrudRequest.create(
                GeneratedInput(
                    values={
                        "email": email,
                        "name": "Created",
                        "group": "ops",
                        "score": 80,
                    },
                    present_fields=frozenset({"email", "name", "group", "score"}),
                )
            ),
            authorization=_authorization("create"),
            uow_factory=self.uow_factory,
        )

    async def _update(
        self,
        result: GeneratedMutationResult,
        email: str,
        *,
        concurrency_token: str | None = None,
        concurrency_required: bool = False,
    ) -> GeneratedMutationResult:
        return await _execute(
            api=self.api,
            executor=self.executor,
            request=GeneratedCrudRequest.update_partial(
                result.identity,
                GeneratedInput(values={"email": email}, present_fields=frozenset({"email"})),
                concurrency_token=concurrency_token,
            ),
            authorization=_authorization("update", result.identity),
            uow_factory=self.uow_factory,
            concurrency_required=concurrency_required,
        )

    async def _delete(self, result: GeneratedMutationResult) -> GeneratedMutationResult:
        assert result.record is not None
        token = self.tokens.issue(
            "users", result.identity, self.version_provider.version_for(result.record)
        )
        return await _execute(
            api=self.api,
            executor=self.executor,
            request=GeneratedCrudRequest.delete(result.identity, concurrency_token=token),
            authorization=_authorization("delete", result.identity),
            uow_factory=self.uow_factory,
            concurrency_required=True,
        )


class ContactSchema(BaseModel):
    name: str
    age: int
    nickname: str | None = None


def _tokens() -> ConcurrencyTokenService:
    token_service = TokenService.single_key(
        key_id="primary",
        value=SecretValue("x" * 32),
        admin_id="admin",
    )
    return ConcurrencyTokenService(token_service)


def _api(data_source: SQLAlchemyDataSource) -> CompiledResourceApi:
    definition = ResourceApiDefinition(
        exposure=ApiExposure.CRUD,
        read_fields=("id", "email", "name", "group", "score", "version"),
        create_fields=("email", "name", "group", "score"),
        update_fields=("email", "name", "group", "score"),
    )
    return CompiledResourceApi(
        resource_id="users",
        definition=definition,
        operations=definition.operations,
        read_fields=definition.read_fields,
        create_fields=definition.create_fields,
        update_fields=definition.update_fields,
        identity_fields=data_source.identity_fields,
        filters=(),
        field_definitions=data_source.field_definitions,
    )


def _authorization(operation: str, identity: RecordIdentity | None = None) -> OperationAuthorization:
    requirement = PermissionRequirement.all_of(f"admin.resources.users.{operation}")
    return OperationAuthorization.for_requirement(
        admin_id="admin",
        resource_id="users",
        operation=operation,
        principal_id="user-1",
        requirement=requirement,
        target_identity=identity,
    )


def _context(authorization: OperationAuthorization) -> OperationContext:
    return OperationContext(
        deadline=None,
        cancellation=CancellationContext(),
        request_id="d1-source-smoke",
        operation_id=new_operation_id(),
        principal_id=authorization.principal_id,
        admin_id=authorization.admin_id,
        resource_id=authorization.resource_id,
        operation=authorization.operation,
        permissions=authorization.permissions,
        permission_requirement=authorization.requirement,
    )


async def _execute(
    *,
    api: CompiledResourceApi,
    executor: object,
    request: GeneratedCrudRequest,
    authorization: OperationAuthorization,
    uow_factory: SQLAlchemyOperationUnitOfWorkFactory,
    concurrency_required: bool = False,
) -> GeneratedMutationResult:
    context = _context(authorization)
    plan = build_generated_operation_plan(
        api,
        request,
        authorization,
        executor,
        concurrency_required=concurrency_required,
    )
    with activate_operation_context(context):
        result = await run_operation_plan(plan, context, unit_of_work_factory=uow_factory)
    assert isinstance(result, GeneratedMutationResult)
    return result


async def _plain_route(_request: object) -> PlainTextResponse:
    return PlainTextResponse("d1-ok")


async def _stream_chunks():
    yield b"chunk-1"
    yield b"chunk-2"


async def _stream_route(_request: object) -> StreamingResponse:
    return StreamingResponse(_stream_chunks())


async def main() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as session:
        session.add_all(ContractUser(**dict(record)) for record in READ_FIXTURE)
        await session.commit()

    persistence_harness = SQLAlchemyConformanceHarness(session_factory)
    persistence_harnesses = {
        PERSISTENCE_READ.name: persistence_harness,
        PERSISTENCE_WRITE.name: persistence_harness,
        PERSISTENCE_RELATIONSHIPS.name: persistence_harness,
        TRANSACTIONS_ROOT_UOW.name: persistence_harness,
        CONCURRENCY_ATOMIC_OPTIMISTIC.name: persistence_harness,
    }

    schema_harness = SchemaConformanceHarness(
        adapter=PydanticSchemaAdapter(),
        schema=ContactSchema,
        expected_field_names=("name", "age", "nickname"),
        valid_input={"name": "Ada", "age": 36},
        invalid_input={"name": "Ada", "age": "not-an-int"},
        serializable_input=ContactSchema(name="Ada", age=36),
        expected_serialized_output={"name": "Ada", "age": 36, "nickname": None},
        partial_input={"nickname": "Countess"},
        expected_partial_output={"nickname": "Countess"},
    )
    schema_harnesses = {
        SCHEMA_FIELD_INTROSPECTION.name: schema_harness,
        SCHEMA_INPUT_VALIDATION.name: schema_harness,
        SCHEMA_OUTPUT_SERIALIZATION.name: schema_harness,
        SCHEMA_PARTIAL_UPDATE.name: schema_harness,
    }

    web_app = Starlette(
        routes=[
            Route("/d1-route", _plain_route),
            Route("/d1-stream", _stream_route),
        ]
    )
    web_harness = WebConformanceHarness(
        app=web_app,
        route_path="/d1-route",
        expected_route_status=200,
        expected_route_body=b"d1-ok",
        streaming_path="/d1-stream",
    )
    web_harnesses = {
        WEB_ASGI.name: web_harness,
        WEB_HTTP_ROUTING.name: web_harness,
        WEB_STREAMING_RESPONSE.name: web_harness,
    }

    results = (
        await run_integration_conformance(
            descriptor=SQLALCHEMY_INTEGRATION,
            harnesses=persistence_harnesses,
            specs=CANONICAL_CONFORMANCE_SPEC_REGISTRY,
        ),
        await run_integration_conformance(
            descriptor=PYDANTIC_INTEGRATION,
            harnesses=schema_harnesses,
            specs=CANONICAL_CONFORMANCE_SPEC_REGISTRY,
        ),
        await run_integration_conformance(
            descriptor=STARLETTE_INTEGRATION,
            harnesses=web_harnesses,
            specs=CANONICAL_CONFORMANCE_SPEC_REGISTRY,
        ),
    )
    rows = conformance_matrix_rows(results)
    assert len(rows) == 12
    assert all(result.passed for result in results)
    assert all(row.passed for row in rows)
    for row in rows:
        print(
            f"{row.integration_id} {row.capability} v{row.contract_version} "
            f"prerequisite={row.prerequisite_valid} behavior={row.behavior_valid}"
        )

    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
