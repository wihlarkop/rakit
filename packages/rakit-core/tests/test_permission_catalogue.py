from rakit_core.definitions import ResourceDefinition
from rakit_core.permission_catalogue import generate_permission_catalogue
from rakit_core.permissions import PermissionRequirement
from rakit_core.relationships import (
    RelationshipCardinality,
    RelationshipDefinition,
    RelationshipKind,
)


def test_generates_access_and_resource_crud_keys() -> None:
    resource = ResourceDefinition(
        resource_id="orders",
        path="/orders",
        label="Orders",
        singular_label="Order",
    )

    catalogue = generate_permission_catalogue(
        admin_id="operations", admin_label="Operations", resources=(resource,)
    )

    keys = {definition.key for definition in catalogue.definitions}
    assert "operations.access" in keys
    assert "operations.resources.orders.read" in keys
    assert "operations.resources.orders.create" in keys
    assert "operations.resources.orders.update" in keys
    assert "operations.resources.orders.delete" in keys


def test_no_resources_still_generates_access_permission() -> None:
    catalogue = generate_permission_catalogue(admin_id="operations", admin_label="Operations")

    keys = {definition.key for definition in catalogue.definitions}
    assert keys == {"operations.access"}


def test_generated_keys_are_stable_and_deterministic() -> None:
    resource = ResourceDefinition(
        resource_id="orders", path="/orders", label="Orders", singular_label="Order"
    )

    first = generate_permission_catalogue(
        admin_id="operations", admin_label="Operations", resources=(resource,)
    )
    second = generate_permission_catalogue(
        admin_id="operations", admin_label="Operations", resources=(resource,)
    )

    assert first == second


def test_only_explicit_relationship_permissions_expand_the_catalogue() -> None:
    default_relationship = RelationshipDefinition(
        relationship_id="customer",
        target_resource_id="customers",
        label="Customer",
        kind=RelationshipKind.MANY_TO_ONE,
        cardinality=RelationshipCardinality.TO_ONE,
    )
    granular_relationship = RelationshipDefinition(
        relationship_id="approvers",
        target_resource_id="users",
        label="Approvers",
        kind=RelationshipKind.MANY_TO_MANY,
        cardinality=RelationshipCardinality.TO_MANY,
        permission=PermissionRequirement.any_of(
            "operations.relationships.approvers.manage",
            "operations.relationships.approvers.override",
        ),
    )
    resource = ResourceDefinition(
        resource_id="orders",
        path="/orders",
        label="Orders",
        singular_label="Order",
        relationships=(default_relationship, granular_relationship),
    )

    catalogue = generate_permission_catalogue(
        admin_id="operations", admin_label="Operations", resources=(resource,)
    )
    keys = {definition.key for definition in catalogue.definitions}

    assert "operations.resources.orders.update" in keys
    assert "operations.relationships.customer.manage" not in keys
    assert "operations.relationships.approvers.manage" in keys
    assert "operations.relationships.approvers.override" in keys
