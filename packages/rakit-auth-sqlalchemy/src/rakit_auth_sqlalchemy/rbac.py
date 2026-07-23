from dataclasses import dataclass

from rakit_core.auth import Principal
from rakit_core.errors import ErrorCode
from rakit_core.permission_catalogue import PermissionCatalogue
from rakit_core.permissions import AuthorizationDecision, PermissionRequirement
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .models import Permission


@dataclass(frozen=True)
class PermissionSyncResult:
    """Counts from one `sync_permissions()` call, for CLI/operator reporting."""

    added: int
    updated: int
    orphaned: int


async def sync_permissions(
    session: AsyncSession, catalogue: PermissionCatalogue
) -> PermissionSyncResult:
    """Add/update permission rows for every definition in `catalogue`, and
    mark any existing row whose key is no longer present as orphaned.

    Never deletes a row: a role may still reference an orphaned permission,
    and silently deleting would silently revoke that grant without record.
    A definition that reappears (e.g. a resource re-enabled) clears the
    orphaned flag on its existing row rather than creating a duplicate.
    Caller is responsible for committing.
    """
    catalogue_keys = {definition.key for definition in catalogue.definitions}
    existing = {row.key: row for row in (await session.execute(select(Permission))).scalars().all()}

    added = 0
    updated = 0
    for definition in catalogue.definitions:
        row = existing.get(definition.key)
        if row is None:
            session.add(
                Permission(key=definition.key, label=definition.label, group=definition.group)
            )
            added += 1
        else:
            row.label = definition.label
            row.group = definition.group
            row.orphaned = False
            updated += 1

    orphaned = 0
    for key, row in existing.items():
        if key not in catalogue_keys:
            row.orphaned = True
            orphaned += 1

    return PermissionSyncResult(added=added, updated=updated, orphaned=orphaned)


class BuiltinAuthorizationPolicy:
    """Allow-only RBAC: default deny, then any role grant already resolved
    into `Principal.permissions` allows. No database access here --
    permission resolution happens once, when the `Principal` is built
    during authentication, not on every authorization check."""

    def __init__(self, *, superuser_bypass: bool = True) -> None:
        self._superuser_bypass = superuser_bypass

    async def authorize(
        self, principal: Principal, requirement: PermissionRequirement
    ) -> AuthorizationDecision:
        if not principal.authenticated:
            return AuthorizationDecision(allowed=False, code=str(ErrorCode.AUTH_UNAUTHENTICATED))
        if requirement.matches(principal, superuser_bypass=self._superuser_bypass):
            return AuthorizationDecision(allowed=True, code="auth.allowed")
        return AuthorizationDecision(allowed=False, code=str(ErrorCode.AUTH_FORBIDDEN))
