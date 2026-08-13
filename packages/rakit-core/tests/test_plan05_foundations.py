import pytest
from rakit_core.actions import ActionScope
from rakit_core.auth import Principal
from rakit_core.bulk import BulkExecutionPolicy, BulkPolicy
from rakit_core.compiler import ApplicationBuilder, compile_application
from rakit_core.datasource import DataSourceCapabilities
from rakit_core.definitions import (
    ActionDefinition,
    EndpointDefinition,
    PageDefinition,
    ResourceDefinition,
    ResourceFieldPolicy,
    RouteDefinition,
)
from rakit_core.endpoints import EndpointMethod
from rakit_core.errors import ErrorCode, RakitError
from rakit_core.identity import RecordIdentity
from rakit_core.mutations import OperationAuthorization
from rakit_core.operations import (
    CancellationContext,
    OperationContext,
    OperationKind,
    OperationPlan,
    execute_operation_plan,
)
from rakit_core.permissions import PermissionRequirement
from rakit_core.query import PageResult, ResourceQuery
from rakit_core.relationships import (
    RelationshipCardinality,
    RelationshipDefinition,
    RelationshipDestructivePolicy,
    RelationshipKind,
)
from rakit_core.transactions import TransactionPolicy


class _DataSource:
    capabilities = DataSourceCapabilities(read=True)
    fields = ("id", "name")
    identity_fields = ("id",)

    async def list(
        self, query: ResourceQuery
    ) -> PageResult:  # pragma: no cover - compiler shape only
        raise AssertionError

    async def count(self, query: ResourceQuery) -> int:  # pragma: no cover - compiler shape only
        raise AssertionError

    async def detail(
        self, identity: RecordIdentity
    ) -> object:  # pragma: no cover - compiler shape only
        raise AssertionError

    def validate_relationship(
        self, definition, target_data_source, association_target_data_source
    ) -> None:
        assert isinstance(target_data_source, _DataSource)
        assert association_target_data_source is None
        assert definition.relationship_id == "customer"


def _resource(resource_id: str, path: str, *, relationships=()) -> ResourceDefinition:
    return ResourceDefinition(
        resource_id=resource_id,
        path=path,
        label=resource_id.title(),
        singular_label=resource_id.title(),
        field_policy=ResourceFieldPolicy(list_fields=("id",), detail_fields=("id",)),
        relationships=relationships,
    )


@pytest.mark.anyio
async def test_operation_plan_reuses_exact_context_authorization_and_typed_result() -> None:
    principal = Principal(
        subject_id="operator",
        authenticated=True,
        permissions=frozenset({"admin.actions.approve.execute"}),
    )
    authorization = OperationAuthorization(
        admin_id="admin",
        resource_id="orders",
        operation="action:approve",
        principal_id="operator",
        permissions=("admin.actions.approve.execute",),
    )
    plan = OperationPlan(
        operation_id="approve",
        kind=OperationKind.ACTION,
        input=3,
        authorization=authorization,
        execute=lambda _context, value: value + 1,
    )
    context = OperationContext(
        deadline=None,
        cancellation=CancellationContext(),
        principal=principal,
        admin_id="admin",
        resource_id="orders",
        operation="action:approve",
        permissions=("admin.actions.approve.execute",),
    )

    assert await execute_operation_plan(plan, context) == 4
    assert plan.operation_id == "approve"


def test_mutating_operation_rejects_read_only_policy() -> None:
    authorization = OperationAuthorization("admin", "orders", "action:x", "operator", ("x",))
    with pytest.raises(ValueError, match="read-only"):
        OperationPlan(
            operation_id="x",
            kind=OperationKind.ACTION,
            input=None,
            authorization=authorization,
            execute=lambda _context, _input: None,
            mutating=True,
        )


@pytest.mark.anyio
async def test_operation_plan_fails_closed_for_context_mismatch() -> None:
    authorization = OperationAuthorization("admin", "orders", "action:x", "operator", ("x",))
    plan = OperationPlan(
        operation_id="x",
        kind=OperationKind.ACTION,
        input=None,
        authorization=authorization,
        execute=lambda _context, _input: None,
    )
    context = OperationContext(
        deadline=None,
        cancellation=CancellationContext(),
        admin_id="other",
        resource_id="orders",
        operation="action:x",
        principal_id="operator",
    )
    with pytest.raises(RakitError) as caught:
        await execute_operation_plan(plan, context)
    assert caught.value.code == ErrorCode.AUTH_FORBIDDEN


def test_compiles_plan05_definitions_routes_and_permission_metadata() -> None:
    relationship = RelationshipDefinition(
        relationship_id="customer",
        target_resource_id="customers",
        label="Customer",
        kind=RelationshipKind.MANY_TO_ONE,
        cardinality=RelationshipCardinality.TO_ONE,
        writable=True,
    )
    builder = ApplicationBuilder(admin_id="operations")
    builder.add_resource(
        _resource("orders", "/orders", relationships=(relationship,)), _DataSource()
    )
    builder.add_resource(_resource("customers", "/customers"), _DataSource())
    builder.add_action(
        ActionDefinition(
            action_id="archive",
            label="Archive",
            scope=ActionScope.BULK,
            resource_id="orders",
            mutating=True,
            transaction_policy=TransactionPolicy.AUTO,
            bulk_policy=BulkPolicy(),
        )
    )
    builder.add_page(PageDefinition(page_id="report", path="/report", label="Report"))
    builder.add_endpoint(
        EndpointDefinition(
            endpoint_id="status",
            path="/api/status",
            methods=(EndpointMethod.GET,),
        )
    )

    compiled = compile_application(builder)

    assert compiled.pages[0].page_id == "report"
    assert compiled.actions[0].action_id == "archive"
    assert compiled.endpoints[0].endpoint_id == "status"
    compiled_relationship = compiled.relationships[0]
    assert compiled_relationship.mutation_permission == PermissionRequirement.all_of(
        "operations.resources.orders.update"
    )
    assert compiled_relationship.route_path == "/orders/{identity}/_relationships/customer"
    assert any(route.path == "/orders/_actions/archive" for route in compiled.routes)
    assert compiled.compiled_actions[0].permission == PermissionRequirement.all_of(
        "operations.actions.archive.execute"
    )
    assert compiled.compiled_pages[0].permission == PermissionRequirement.all_of(
        "operations.pages.report.view"
    )
    assert compiled.compiled_endpoints[0].permission == PermissionRequirement.all_of(
        "operations.endpoints.status.invoke"
    )


def test_destructive_relationship_compiles_target_delete_requirement() -> None:
    relationship = RelationshipDefinition(
        relationship_id="customer",
        target_resource_id="customers",
        label="Customer",
        kind=RelationshipKind.MANY_TO_ONE,
        cardinality=RelationshipCardinality.TO_ONE,
        destructive_policy=RelationshipDestructivePolicy(allow_child_delete=True),
    )
    builder = ApplicationBuilder(admin_id="operations")
    builder.add_resource(
        _resource("orders", "/orders", relationships=(relationship,)), _DataSource()
    )
    builder.add_resource(_resource("customers", "/customers"), _DataSource())

    compiled = compile_application(builder)

    assert compiled.relationships[0].target_delete_permission == PermissionRequirement.all_of(
        "operations.resources.customers.delete"
    )


def test_relationship_permission_override_and_missing_target_fail_closed() -> None:
    override = PermissionRequirement.all_of("operations.relationships.customer.manage")
    relationship = RelationshipDefinition(
        relationship_id="customer",
        target_resource_id="customers",
        label="Customer",
        kind=RelationshipKind.MANY_TO_ONE,
        cardinality=RelationshipCardinality.TO_ONE,
        readable=False,
        permission=override,
    )
    builder = ApplicationBuilder(admin_id="operations")
    builder.add_resource(
        _resource("orders", "/orders", relationships=(relationship,)), _DataSource()
    )
    builder.add_resource(_resource("customers", "/customers"), _DataSource())
    assert compile_application(builder).relationships[0].mutation_permission is override

    missing_target = ApplicationBuilder()
    missing_target.add_resource(
        _resource("orders", "/orders", relationships=(relationship,)), _DataSource()
    )
    with pytest.raises(RakitError) as caught:
        compile_application(missing_target)
    assert caught.value.details["reason"] == "target_resource_not_registered"


def test_plan05_definition_routes_collide_and_framework_segments_remain_reserved() -> None:
    builder = ApplicationBuilder()
    builder.add_page(PageDefinition(page_id="status", path="/status", label="Status"))
    builder.add_route(
        RouteDefinition(
            route_name="host.status",
            methods=("GET",),
            path="/status",
            owner_id="host",
        )
    )
    with pytest.raises(RakitError) as collision:
        compile_application(builder)
    assert collision.value.code == ErrorCode.CONFIG_ROUTE_COLLISION

    reserved = ApplicationBuilder()
    reserved.add_route(
        RouteDefinition(
            route_name="host.action",
            methods=("GET",),
            path="/orders/{identity}/_actions/export",
            owner_id="host",
        )
    )
    with pytest.raises(RakitError) as caught:
        compile_application(reserved)
    assert caught.value.code == ErrorCode.CONFIG_RESERVED_PATH


def test_bulk_defaults_are_safe() -> None:
    policy = BulkPolicy()
    assert policy.execution is BulkExecutionPolicy.ATOMIC
    assert policy.confirmation_threshold == 25
    assert policy.synchronous_maximum == 1000
    assert policy.require_concurrency_snapshot is True
