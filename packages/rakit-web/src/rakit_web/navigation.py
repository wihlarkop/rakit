"""Permission-aware navigation model for the built-in admin shell."""

from collections.abc import Callable
from dataclasses import dataclass

from rakit_core.auth import Principal
from rakit_core.definitions import CompiledPageDefinition, ResourceDefinition
from rakit_core.permissions import PermissionRequirement
from starlette.requests import Request

from ._paths import mounted_path
from .security.authentication import admin_relative_path


@dataclass(frozen=True)
class NavigationItem:
    label: str
    path: str
    active: bool


@dataclass(frozen=True)
class AdminNavigation:
    title: str
    dashboard: NavigationItem
    resources: tuple[NavigationItem, ...]
    pages: tuple[NavigationItem, ...]


def build_navigation_provider(
    *,
    title: str,
    admin_id: str,
    resources: tuple[ResourceDefinition, ...],
    pages: tuple[CompiledPageDefinition, ...],
    auth_enabled: bool,
    superuser_bypass: bool,
) -> Callable[[Request], AdminNavigation]:
    """Build request-aware navigation using the same permission model as routes."""

    resource_requirements = {
        str(resource.resource_id): PermissionRequirement.all_of(
            f"{admin_id}.resources.{resource.resource_id}.read"
        )
        for resource in resources
    }

    def allowed(
        principal: Principal | None,
        requirement: PermissionRequirement | None,
    ) -> bool:
        if requirement is None or not auth_enabled:
            return True
        return bool(
            principal is not None
            and requirement.matches(principal, superuser_bypass=superuser_bypass)
        )

    def provider(request: Request) -> AdminNavigation:
        principal_value = request.scope.get("state", {}).get("principal")
        principal = principal_value if isinstance(principal_value, Principal) else None
        current_path = admin_relative_path(request)

        def item(label: str, path: str) -> NavigationItem:
            active = current_path == path or (path != "/" and current_path.startswith(f"{path}/"))
            return NavigationItem(
                label=label,
                path=mounted_path(request, path),
                active=active,
            )

        visible_resources = tuple(
            item(resource.label, resource.path)
            for resource in resources
            if allowed(principal, resource_requirements[str(resource.resource_id)])
        )
        visible_pages = tuple(
            item(page.definition.label, page.definition.path)
            for page in pages
            if allowed(principal, page.permission)
        )
        return AdminNavigation(
            title=title,
            dashboard=item("Dashboard", "/"),
            resources=visible_resources,
            pages=visible_pages,
        )

    return provider


__all__ = ["AdminNavigation", "NavigationItem", "build_navigation_provider"]
