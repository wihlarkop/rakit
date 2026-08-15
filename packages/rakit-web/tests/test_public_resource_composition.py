"""Public ResourceAdmin composition for relationships and resource-owned actions."""

import pytest
from rakit_core.actions import (
    ActionDefinition,
    ActionScope,
    ActionSuccess,
    DomainActionExecutor,
)
from rakit_core.admin_types import ResourceAdmin
from rakit_core.bulk import BulkPolicy
from rakit_core.datasource import DataSourceCapabilities
from rakit_core.errors import RakitError
from rakit_core.identity import RecordIdentity
from rakit_core.query import PageResult, ResourceQuery
from rakit_core.relationships import (
    RelationshipCardinality,
    RelationshipDefinition,
    RelationshipKind,
)
from rakit_web.admin import Admin


class _DataSource:
    capabilities = DataSourceCapabilities(read=True)
    fields = ("id", "name")
    identity_fields = ("id",)

    async def list(self, query: ResourceQuery) -> PageResult:
        raise AssertionError(query)

    async def count(self, query: ResourceQuery) -> int:
        raise AssertionError(query)

    async def detail(self, identity: RecordIdentity) -> object:
        raise AssertionError(identity)

    def validate_relationship(
        self,
        definition: RelationshipDefinition,
        target_data_source: object,
        association_target_data_source: object | None,
    ) -> None:
        assert definition.relationship_id == "customer"
        assert isinstance(target_data_source, _DataSource)
        assert association_target_data_source is None


def _executor() -> DomainActionExecutor:
    return DomainActionExecutor(lambda _context: ActionSuccess())


class CustomersAdmin(ResourceAdmin):
    resource_id = "customers"
    path = "/customers"
    label = "Customers"
    singular_label = "Customer"
    list_fields = ("id", "name")
    detail_fields = ("id", "name")
    data_source = _DataSource()


class OrdersAdmin(ResourceAdmin):
    resource_id = "orders"
    path = "/orders"
    label = "Orders"
    singular_label = "Order"
    list_fields = ("id", "name")
    detail_fields = ("id", "name")
    data_source = _DataSource()
    relationships = (
        RelationshipDefinition(
            relationship_id="customer",
            target_resource_id="customers",
            label="Customer",
            kind=RelationshipKind.MANY_TO_ONE,
            cardinality=RelationshipCardinality.TO_ONE,
        ),
    )
    actions = (
        ActionDefinition(
            action_id="export",
            label="Export",
            scope=ActionScope.RESOURCE,
            resource_id="orders",
            executor=_executor(),
        ),
        ActionDefinition(
            action_id="inspect",
            label="Inspect",
            scope=ActionScope.RECORD,
            resource_id="orders",
            executor=_executor(),
        ),
        ActionDefinition(
            action_id="archive_selected",
            label="Archive selected",
            scope=ActionScope.BULK,
            resource_id="orders",
            executor=_executor(),
            bulk_policy=BulkPolicy(require_concurrency_snapshot=False),
        ),
    )


def test_resource_admin_composes_relationships_and_actions_into_compiled_graph() -> None:
    admin = Admin(title="Operations", debug=True)
    admin.register(CustomersAdmin)
    admin.register(OrdersAdmin)

    compiled = admin.compile()

    orders = next(resource for resource in compiled.resources if resource.resource_id == "orders")
    assert orders.relationship_ids == ("customer",)
    assert {str(action.action_id) for action in compiled.actions} == {
        "export",
        "inspect",
        "archive_selected",
    }
    assert {
        route.path
        for route in compiled.routes
        if route.route_name.startswith("resource:orders:action:")
    } == {
        "/orders/_actions/export",
        "/orders/{identity}/_actions/inspect",
        "/orders/_actions/archive_selected",
    }
    assert compiled.relationships[0].route_path == "/orders/{identity}/_relationships/customer"


def test_resource_action_owner_mismatch_fails_before_builder_mutation() -> None:
    class InvalidAdmin(ResourceAdmin):
        resource_id = "invoices"
        path = "/invoices"
        label = "Invoices"
        singular_label = "Invoice"
        list_fields = ("id", "name")
        detail_fields = ("id", "name")
        data_source = _DataSource()
        actions = (
            ActionDefinition(
                action_id="bad_owner",
                label="Bad owner",
                scope=ActionScope.RESOURCE,
                resource_id="orders",
                executor=_executor(),
            ),
        )

    admin = Admin(title="Operations", debug=True)

    with pytest.raises(RakitError) as caught:
        admin.register(InvalidAdmin)

    assert caught.value.details["reason"] == "resource_owner_mismatch"
    assert not any(resource.resource_id == "invoices" for resource in admin.builder.resources)


def test_duplicate_public_action_id_fails_before_second_resource_registration() -> None:
    class FirstAdmin(ResourceAdmin):
        resource_id = "first"
        path = "/first"
        label = "First"
        singular_label = "First"
        list_fields = ("id", "name")
        detail_fields = ("id", "name")
        data_source = _DataSource()
        actions = (
            ActionDefinition(
                action_id="shared",
                label="Shared",
                scope=ActionScope.RESOURCE,
                resource_id="first",
                executor=_executor(),
            ),
        )

    class SecondAdmin(ResourceAdmin):
        resource_id = "second"
        path = "/second"
        label = "Second"
        singular_label = "Second"
        list_fields = ("id", "name")
        detail_fields = ("id", "name")
        data_source = _DataSource()
        actions = (
            ActionDefinition(
                action_id="shared",
                label="Shared",
                scope=ActionScope.RESOURCE,
                resource_id="second",
                executor=_executor(),
            ),
        )

    admin = Admin(title="Operations", debug=True)
    admin.register(FirstAdmin)

    with pytest.raises(RakitError) as caught:
        admin.register(SecondAdmin)

    assert caught.value.details["reason"] == "duplicate_action"
    assert {resource.resource_id for resource in admin.builder.resources} == {"first"}


def test_page_action_cannot_be_declared_on_resource_admin() -> None:
    class InvalidAdmin(ResourceAdmin):
        resource_id = "orders"
        path = "/orders"
        label = "Orders"
        singular_label = "Order"
        list_fields = ("id", "name")
        detail_fields = ("id", "name")
        data_source = _DataSource()
        actions = (
            ActionDefinition(
                action_id="page_only",
                label="Page only",
                scope=ActionScope.PAGE,
                page_id="dashboard",
                executor=_executor(),
            ),
        )

    admin = Admin(title="Operations", debug=True)
    with pytest.raises(RakitError) as caught:
        admin.register(InvalidAdmin)
    assert caught.value.details["reason"] == "page_action_not_resource_owned"
