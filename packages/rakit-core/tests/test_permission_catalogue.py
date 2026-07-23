from rakit_core.definitions import ResourceDefinition
from rakit_core.permission_catalogue import generate_permission_catalogue


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
