from pydantic import BaseModel, ConfigDict

from rakit_core.actions import ActionDefinition
from rakit_core.definitions import (
    EndpointDefinition,
    PageDefinition,
    ResourceDefinition,
)

_RESOURCE_OPERATIONS = ("read", "create", "update", "delete")


class PermissionDefinition(BaseModel):
    """One generated, stable permission key -- never hand-authored, always
    derived from a compiled admin's resources/pages/actions/endpoints so the
    key stays in sync with what's actually registered."""

    model_config = ConfigDict(frozen=True)

    key: str
    label: str
    group: str


class PermissionCatalogue(BaseModel):
    """The complete, frozen set of permission definitions generated for one
    compiled admin. Synchronizing this against storage (`rakit-auth-sqlalchemy`'s
    `sync_permissions()`) never silently deletes a row for a key no longer
    present here -- see that function's docstring."""

    model_config = ConfigDict(frozen=True)

    definitions: tuple[PermissionDefinition, ...] = ()


def generate_permission_catalogue(
    *,
    admin_id: str,
    admin_label: str,
    resources: tuple[ResourceDefinition, ...] = (),
    pages: tuple[PageDefinition, ...] = (),
    actions: tuple[ActionDefinition, ...] = (),
    endpoints: tuple[EndpointDefinition, ...] = (),
) -> PermissionCatalogue:
    """Generate the permission catalogue for one compiled admin.

    `{admin_id}.access` is always generated. Resource CRUD keys
    (`{admin_id}.resources.{resource_id}.read|create|update|delete`) are
    generated unconditionally for every compiled resource, even though
    Plan 02/03 only implement read -- this keeps permission keys stable
    across later plans that add write operations, rather than growing the
    catalogue (and forcing a resync) when create/update/delete ship.

    Field- and relationship-level permission keys are intentionally not
    generated here: `ResourceFieldPolicy` has no per-field permission
    configuration yet (that is a later plan's concern), so there is nothing
    to derive them from. Pages/actions/endpoints accept empty tuples today
    since `CompiledApplication` does not yet populate them (later plans);
    this function is already shaped to generate their keys once it does.
    """
    definitions = [
        PermissionDefinition(
            key=f"{admin_id}.access", label=f"Access {admin_label}", group=admin_label
        )
    ]
    for resource in resources:
        for operation in _RESOURCE_OPERATIONS:
            definitions.append(
                PermissionDefinition(
                    key=f"{admin_id}.resources.{resource.resource_id}.{operation}",
                    label=f"{operation.capitalize()} {resource.label}",
                    group=resource.label,
                )
            )
        for relationship in resource.relationships:
            if relationship.permission is None:
                continue
            for key in relationship.permission.permissions:
                definitions.append(
                    PermissionDefinition(
                        key=key,
                        label=f"Manage {relationship.label}",
                        group=resource.label,
                    )
                )
    for page in pages:
        definitions.append(
            PermissionDefinition(
                key=f"{admin_id}.pages.{page.page_id}.view",
                label=f"View {page.label}",
                group=page.label,
            )
        )
    for action in actions:
        definitions.append(
            PermissionDefinition(
                key=f"{admin_id}.actions.{action.action_id}.execute",
                label=f"Execute {action.label}",
                group=action.label,
            )
        )
    for endpoint in endpoints:
        definitions.append(
            PermissionDefinition(
                key=f"{admin_id}.endpoints.{endpoint.endpoint_id}.invoke",
                label=f"Invoke {endpoint.endpoint_id}",
                group="Endpoints",
            )
        )
    unique_definitions: dict[str, PermissionDefinition] = {}
    for definition in definitions:
        unique_definitions.setdefault(definition.key, definition)
    return PermissionCatalogue(definitions=tuple(unique_definitions.values()))
