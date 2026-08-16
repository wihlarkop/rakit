from collections.abc import AsyncIterator

import pytest
from rakit_core.concurrency import AttributeVersionProvider, ConcurrencyTokenService
from rakit_core.config import SecretValue
from rakit_core.crypto import TokenService
from rakit_core.definitions import ResourceFieldPolicy
from rakit_core.errors import ErrorCode, RakitError
from rakit_core.generated_api import (
    ApiExposure,
    CompiledResourceApi,
    ResourceApiDefinition,
)
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
from rakit_sqlalchemy.datasource import SQLAlchemyDataSource
from rakit_sqlalchemy.generated import SQLAlchemyGeneratedResourceExecutorProvider
from rakit_sqlalchemy.uow import SQLAlchemyOperationUnitOfWorkFactory
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "generated_rest_users"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str]
    version: Mapped[int] = mapped_column(default=1)


@pytest.fixture
async def session_factory() -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    yield async_sessionmaker(engine, expire_on_commit=False)
    await engine.dispose()


def _datasource(session_factory: async_sessionmaker[AsyncSession]) -> SQLAlchemyDataSource:
    return SQLAlchemyDataSource(
        model=User,
        session_factory=session_factory,
        field_policy=ResourceFieldPolicy(
            list_fields=("id", "email", "version"),
            detail_fields=("id", "email", "version"),
            sort_fields=("email",),
        ),
    )


def _api(data_source: SQLAlchemyDataSource) -> CompiledResourceApi:
    definition = ResourceApiDefinition(
        exposure=ApiExposure.CRUD,
        read_fields=("id", "email", "version"),
        create_fields=("email",),
        update_fields=("email",),
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
        request_id="req-1",
        operation_id=new_operation_id(),
        principal_id=authorization.principal_id,
        admin_id=authorization.admin_id,
        resource_id=authorization.resource_id,
        operation=authorization.operation,
        permissions=authorization.permissions,
        permission_requirement=authorization.requirement,
    )


def _tokens() -> ConcurrencyTokenService:
    token_service = TokenService.single_key(
        key_id="primary",
        value=SecretValue("x" * 32),
        admin_id="admin",
    )
    return ConcurrencyTokenService(token_service)


async def _execute(
    *,
    api: CompiledResourceApi,
    executor,
    request: GeneratedCrudRequest,
    authorization: OperationAuthorization,
    uow_factory: SQLAlchemyOperationUnitOfWorkFactory,
    concurrency_required: bool = False,
):
    context = _context(authorization)
    plan = build_generated_operation_plan(
        api,
        request,
        authorization,
        executor,
        concurrency_required=concurrency_required,
    )
    with activate_operation_context(context):
        return await run_operation_plan(plan, context, unit_of_work_factory=uow_factory)


@pytest.mark.anyio
async def test_generated_executor_create_update_and_delete_share_root_uow(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    data_source = _datasource(session_factory)
    version_provider = AttributeVersionProvider("version")
    concurrency_tokens = _tokens()
    executor = SQLAlchemyGeneratedResourceExecutorProvider(model=User).build(
        GeneratedResourceExecutorContext(
            resource_id="users",
            data_source=data_source,
            concurrency_provider=version_provider,
            concurrency_tokens=concurrency_tokens,
        )
    )
    api = _api(data_source)
    uow_factory = SQLAlchemyOperationUnitOfWorkFactory(session_factory)

    created = await _execute(
        api=api,
        executor=executor,
        request=GeneratedCrudRequest.create(
            GeneratedInput(
                values={"email": "first@example.com"},
                present_fields=frozenset({"email"}),
            )
        ),
        authorization=_authorization("create"),
        uow_factory=uow_factory,
    )
    assert isinstance(created, GeneratedMutationResult)
    assert created.identity.values["id"] == 1
    assert created.record is not None
    assert created.record.version == 1

    update_token = concurrency_tokens.issue(
        "users",
        created.identity,
        version_provider.version_for(created.record),
    )
    updated = await _execute(
        api=api,
        executor=executor,
        request=GeneratedCrudRequest.update_partial(
            created.identity,
            GeneratedInput(
                values={"email": "next@example.com"},
                present_fields=frozenset({"email"}),
            ),
            concurrency_token=update_token,
        ),
        authorization=_authorization("update", created.identity),
        uow_factory=uow_factory,
        concurrency_required=True,
    )
    assert isinstance(updated, GeneratedMutationResult)
    assert updated.record is not None
    assert updated.record.email == "next@example.com"
    assert updated.record.version == 2

    with pytest.raises(RakitError) as stale:
        await _execute(
            api=api,
            executor=executor,
            request=GeneratedCrudRequest.update_partial(
                created.identity,
                GeneratedInput(
                    values={"email": "stale@example.com"},
                    present_fields=frozenset({"email"}),
                ),
                concurrency_token=update_token,
            ),
            authorization=_authorization("update", created.identity),
            uow_factory=uow_factory,
            concurrency_required=True,
        )
    assert stale.value.code == ErrorCode.RESOURCE_CONFLICT

    assert updated.record is not None
    delete_token = concurrency_tokens.issue(
        "users",
        updated.identity,
        version_provider.version_for(updated.record),
    )
    deleted = await _execute(
        api=api,
        executor=executor,
        request=GeneratedCrudRequest.delete(
            updated.identity,
            concurrency_token=delete_token,
        ),
        authorization=_authorization("delete", updated.identity),
        uow_factory=uow_factory,
        concurrency_required=True,
    )
    assert isinstance(deleted, GeneratedMutationResult)
    assert deleted.record is None

    async with session_factory() as session:
        assert await session.scalar(select(User).where(User.id == 1)) is None


@pytest.mark.anyio
async def test_generated_executor_rejects_execution_without_sqlalchemy_root_uow(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    data_source = _datasource(session_factory)
    executor = SQLAlchemyGeneratedResourceExecutorProvider(model=User).build(
        GeneratedResourceExecutorContext(resource_id="users", data_source=data_source)
    )
    request = GeneratedCrudRequest.create(
        GeneratedInput(
            values={"email": "no-uow@example.com"},
            present_fields=frozenset({"email"}),
        )
    )
    context = _context(_authorization("create"))

    with pytest.raises(RakitError) as captured:
        await executor.execute(context, request)

    assert captured.value.details["reason"] == "generated_api_sqlalchemy_uow_required"
