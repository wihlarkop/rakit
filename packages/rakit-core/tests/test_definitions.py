import pytest
from pydantic import ValidationError
from rakit_core.definitions import ResourceDefinition, RouteDefinition


def test_resource_id_path_and_label_are_independent() -> None:
    definition = ResourceDefinition(
        resource_id="users",
        path="/people",
        label="User Accounts",
        singular_label="User Account",
    )
    assert definition.resource_id == "users"
    assert definition.path == "/people"


def test_route_path_must_be_absolute() -> None:
    with pytest.raises(ValidationError):
        RouteDefinition(
            route_name="rakit.operations.resources.users.list",
            methods=("GET",),
            path="users",
            owner_id="users",
        )
