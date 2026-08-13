from collections.abc import AsyncIterator

import pytest
from rakit_auth_sqlalchemy.models import Base, Permission
from rakit_auth_sqlalchemy.rbac import BuiltinAuthorizationPolicy, sync_permissions
from rakit_core.auth import Principal
from rakit_core.definitions import ResourceDefinition
from rakit_core.permission_catalogue import PermissionCatalogue, PermissionDefinition
from rakit_core.permissions import PermissionRequirement
from rakit_core.relationships import (
    RelationshipCardinality,
    RelationshipDefinition,
    RelationshipKind,
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine


@pytest.fixture
async def session_factory() -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    yield factory
    await engine.dispose()


async def test_sync_permissions_adds_new_definitions(session_factory) -> None:
    catalogue = PermissionCatalogue(
        definitions=(
            PermissionDefinition(
                key="operations.resources.users.read", label="View Users", group="Users"
            ),
        )
    )
    async with session_factory() as session:
        result = await sync_permissions(session, catalogue)
        await session.commit()

    assert result.added == 1
    assert result.updated == 0
    assert result.orphaned == 0

    async with session_factory() as session:
        permission = (await session.execute(select(Permission))).scalar_one()
        assert permission.key == "operations.resources.users.read"
        assert permission.label == "View Users"
        assert permission.orphaned is False


async def test_sync_result_counts_updated_and_orphaned(session_factory) -> None:
    async with session_factory() as session:
        await sync_permissions(
            session,
            PermissionCatalogue(
                definitions=(
                    PermissionDefinition(key="operations.access", label="Old", group="Old"),
                    PermissionDefinition(
                        key="operations.resources.users.read", label="Read", group="Users"
                    ),
                )
            ),
        )
        await session.commit()

    async with session_factory() as session:
        result = await sync_permissions(
            session,
            PermissionCatalogue(
                definitions=(
                    PermissionDefinition(key="operations.access", label="New", group="New"),
                )
            ),
        )
        await session.commit()

    assert result.added == 0
    assert result.updated == 1
    assert result.orphaned == 1


async def test_removed_permission_is_marked_orphaned(session_factory) -> None:
    async with session_factory() as session:
        await sync_permissions(
            session,
            PermissionCatalogue(
                definitions=(
                    PermissionDefinition(
                        key="operations.resources.users.read",
                        label="View Users",
                        group="Users",
                    ),
                )
            ),
        )
        await session.commit()

    async with session_factory() as session:
        await sync_permissions(session, PermissionCatalogue(definitions=()))
        await session.commit()

    async with session_factory() as session:
        permission = (await session.execute(select(Permission))).scalar_one()
        assert permission.orphaned is True


async def test_resync_clears_orphaned_flag_when_definition_returns(session_factory) -> None:
    definition = PermissionDefinition(
        key="operations.resources.users.read", label="View Users", group="Users"
    )
    async with session_factory() as session:
        await sync_permissions(session, PermissionCatalogue(definitions=(definition,)))
        await sync_permissions(session, PermissionCatalogue(definitions=()))
        await session.commit()

    async with session_factory() as session:
        await sync_permissions(session, PermissionCatalogue(definitions=(definition,)))
        await session.commit()

    async with session_factory() as session:
        permission = (await session.execute(select(Permission))).scalar_one()
    assert permission.orphaned is False


async def test_removing_a_granular_relationship_permission_orphans_its_catalogue_key(
    session_factory,
) -> None:
    relationship = RelationshipDefinition(
        relationship_id="approvers",
        target_resource_id="users",
        label="Approvers",
        kind=RelationshipKind.MANY_TO_MANY,
        cardinality=RelationshipCardinality.TO_MANY,
        permission=PermissionRequirement.all_of("operations.relationships.approvers.manage"),
    )
    configured = ResourceDefinition(
        resource_id="orders",
        path="/orders",
        label="Orders",
        singular_label="Order",
        relationships=(relationship,),
    )
    removed = configured.model_copy(update={"relationships": ()})
    from rakit_core.permission_catalogue import generate_permission_catalogue

    async with session_factory() as session:
        await sync_permissions(
            session,
            generate_permission_catalogue(
                admin_id="operations", admin_label="Operations", resources=(configured,)
            ),
        )
        await session.commit()

    async with session_factory() as session:
        await sync_permissions(
            session,
            generate_permission_catalogue(
                admin_id="operations", admin_label="Operations", resources=(removed,)
            ),
        )
        await session.commit()

    async with session_factory() as session:
        permission = await session.scalar(
            select(Permission).where(Permission.key == "operations.relationships.approvers.manage")
        )
    assert permission is not None
    assert permission.orphaned is True


async def test_sync_updates_label_and_group_for_existing_key(session_factory) -> None:
    async with session_factory() as session:
        await sync_permissions(
            session,
            PermissionCatalogue(
                definitions=(
                    PermissionDefinition(key="operations.access", label="Old", group="Old"),
                )
            ),
        )
        await session.commit()

    async with session_factory() as session:
        await sync_permissions(
            session,
            PermissionCatalogue(
                definitions=(
                    PermissionDefinition(
                        key="operations.access", label="New Label", group="New Group"
                    ),
                )
            ),
        )
        await session.commit()

    async with session_factory() as session:
        permission = (await session.execute(select(Permission))).scalar_one()
        assert permission.label == "New Label"
        assert permission.group == "New Group"


async def test_sync_never_deletes_a_permission_row(session_factory) -> None:
    async with session_factory() as session:
        await sync_permissions(
            session,
            PermissionCatalogue(
                definitions=(
                    PermissionDefinition(key="operations.access", label="Access", group="Admin"),
                )
            ),
        )
        await sync_permissions(session, PermissionCatalogue(definitions=()))
        await session.commit()

    async with session_factory() as session:
        count = len((await session.execute(select(Permission))).scalars().all())
        assert count == 1


async def test_unauthenticated_principal_is_denied() -> None:
    policy = BuiltinAuthorizationPolicy()
    decision = await policy.authorize(
        Principal(), PermissionRequirement.all_of("operations.access")
    )
    assert decision.allowed is False
    assert decision.code == "auth.unauthenticated"


async def test_authenticated_principal_with_permission_is_allowed() -> None:
    policy = BuiltinAuthorizationPolicy()
    principal = Principal(
        subject_id="1", authenticated=True, permissions=frozenset({"operations.access"})
    )
    decision = await policy.authorize(principal, PermissionRequirement.all_of("operations.access"))
    assert decision.allowed is True


async def test_authenticated_principal_without_permission_is_denied() -> None:
    policy = BuiltinAuthorizationPolicy()
    principal = Principal(subject_id="1", authenticated=True)
    decision = await policy.authorize(principal, PermissionRequirement.all_of("operations.access"))
    assert decision.allowed is False
    assert decision.code == "auth.forbidden"


async def test_superuser_bypass_is_configurable() -> None:
    principal = Principal(subject_id="1", authenticated=True, is_superuser=True)
    requirement = PermissionRequirement.all_of("operations.access")

    bypass_enabled = BuiltinAuthorizationPolicy(superuser_bypass=True)
    assert (await bypass_enabled.authorize(principal, requirement)).allowed is True

    bypass_disabled = BuiltinAuthorizationPolicy(superuser_bypass=False)
    assert (await bypass_disabled.authorize(principal, requirement)).allowed is False
