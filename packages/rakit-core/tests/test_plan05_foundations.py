import pytest
from pydantic import BaseModel
from rakit_core.actions import (
    ActionDefinition,
    ActionRedirect,
    ActionRefresh,
    ActionRejected,
    ActionScope,
    ActionSuccess,
    DomainActionExecutor,
)
from rakit_core.auth import Principal
from rakit_core.bulk import BulkExecutionPolicy, BulkPolicy
from rakit_core.compiler import ApplicationBuilder, compile_application
from rakit_core.datasource import DataSourceCapabilities
from rakit_core.definitions import (
    EndpointDefinition,
    PageDefinition,
    ResourceDefinition,
    ResourceFieldPolicy,
    RouteDefinition,
)
from rakit_core.endpoints import (
    EndpointAccessPolicy,
    EndpointMethod,
    EndpointResponseKind,
)
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
    resolve_record_label,
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


def _noop_executor() -> DomainActionExecutor:
    return DomainActionExecutor(lambda _context: ActionSuccess())


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
        permission_requirement=PermissionRequirement.all_of("admin.actions.approve.execute"),
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


@pytest.mark.anyio
async def test_operation_authorization_binds_the_exact_requirement_without_rechecking_rbac(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    expected = PermissionRequirement.any_of("approve", "override")
    authorization = OperationAuthorization(
        "admin",
        "orders",
        "action:approve",
        "operator",
        ("approve", "override"),
        permission_mode="any",
    )
    plan = OperationPlan(
        operation_id="approve",
        kind=OperationKind.ACTION,
        input=None,
        authorization=authorization,
        execute=lambda _context, _input: "ok",
    )
    context = OperationContext(
        deadline=None,
        cancellation=CancellationContext(),
        admin_id="admin",
        resource_id="orders",
        operation="action:approve",
        principal_id="operator",
        permission_requirement=expected,
    )

    monkeypatch.setattr(
        PermissionRequirement,
        "matches",
        lambda _self, _principal: (_ for _ in ()).throw(AssertionError("RBAC was re-run")),
    )
    assert await execute_operation_plan(plan, context) == "ok"

    all_mode_context = OperationContext(
        deadline=None,
        cancellation=CancellationContext(),
        admin_id="admin",
        resource_id="orders",
        operation="action:approve",
        principal_id="operator",
        permission_requirement=PermissionRequirement.all_of("approve", "override"),
    )
    with pytest.raises(RakitError) as caught:
        await execute_operation_plan(plan, all_mode_context)
    assert caught.value.code == ErrorCode.AUTH_FORBIDDEN


@pytest.mark.anyio
async def test_operation_authorization_requires_a_capability_and_binds_record_targets() -> None:
    requirement = PermissionRequirement.all_of("approve")
    target = RecordIdentity(values={"id": 7})
    authorization = OperationAuthorization.for_requirement(
        admin_id="admin",
        resource_id="orders",
        operation="action:approve",
        principal_id="operator",
        requirement=requirement,
        target_identity=target,
    )
    context = OperationContext(
        deadline=None,
        cancellation=CancellationContext(),
        admin_id="admin",
        resource_id="orders",
        operation="action:approve",
        principal_id="operator",
        permission_requirement=requirement,
    )
    plan = OperationPlan(
        operation_id="approve",
        kind=OperationKind.ACTION,
        input=None,
        authorization=authorization,
        target_identity=target,
        execute=lambda _context, _input: "ok",
    )
    assert await execute_operation_plan(plan, context) == "ok"

    missing = OperationPlan(
        operation_id="missing",
        kind=OperationKind.ACTION,
        input=None,
        authorization=None,
        execute=lambda _context, _input: "never",
    )
    with pytest.raises(RakitError) as caught:
        await execute_operation_plan(missing, context)
    assert caught.value.code == ErrorCode.AUTH_FORBIDDEN

    mismatched_target = plan.__class__(
        operation_id=plan.operation_id,
        kind=plan.kind,
        input=plan.input,
        authorization=plan.authorization,
        target_identity=RecordIdentity(values={"id": 8}),
        execute=plan.execute,
    )
    with pytest.raises(RakitError) as caught:
        await execute_operation_plan(mismatched_target, context)
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
            executor=_noop_executor(),
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
    bulk_route = next(route for route in compiled.routes if route.path == "/orders/_actions/archive")
    assert compiled.compiled_actions[0].permission == PermissionRequirement.all_of(
        "operations.actions.archive.execute"
    )
    assert compiled.compiled_pages[0].permission == PermissionRequirement.all_of(
        "operations.pages.report.view"
    )
    assert compiled.compiled_endpoints[0].permission == PermissionRequirement.all_of(
        "operations.endpoints.status.invoke"
    )
    assert compiled.action_routes == ((bulk_route, compiled.compiled_actions[0]),)


def test_page_actions_have_explicit_page_ownership_and_compiled_routes() -> None:
    builder = ApplicationBuilder()
    builder.add_page(PageDefinition(page_id="report", path="/reports", label="Report"))
    builder.add_action(
        ActionDefinition(
            action_id="refresh",
            label="Refresh",
            scope=ActionScope.PAGE,
            page_id="report",
            executor=_noop_executor(),
        )
    )

    compiled = compile_application(builder)
    assert any(route.path == "/reports/_actions/refresh" for route in compiled.routes)
    assert not next(
        route for route in compiled.routes if route.path == "/reports/_actions/refresh"
    ).framework_owned

    with pytest.raises(ValueError, match="page_id"):
        ActionDefinition(action_id="orphan", label="Orphan", scope=ActionScope.PAGE)

    unknown = ApplicationBuilder()
    unknown.add_action(
        ActionDefinition(
            action_id="unknown",
            label="Unknown",
            scope=ActionScope.PAGE,
            page_id="missing",
            executor=_noop_executor(),
        )
    )
    with pytest.raises(RakitError) as caught:
        compile_application(unknown)
    assert caught.value.details["reason"] == "page_owner_not_registered"

    colliding = ApplicationBuilder()
    colliding.add_page(PageDefinition(page_id="report", path="/reports", label="Report"))
    colliding.add_action(
        ActionDefinition(
            action_id="refresh",
            label="Refresh",
            scope=ActionScope.PAGE,
            page_id="report",
            executor=_noop_executor(),
        )
    )
    colliding.add_endpoint(
        EndpointDefinition(
            endpoint_id="same_path",
            path="/reports/_actions/refresh",
            methods=(EndpointMethod.GET,),
        )
    )
    with pytest.raises(RakitError) as caught:
        compile_application(colliding)
    assert caught.value.code == ErrorCode.CONFIG_ROUTE_COLLISION


def test_action_and_endpoint_semantic_contracts_are_explicit() -> None:
    assert ActionSuccess(payload={"ok": True}).payload == {"ok": True}
    assert ActionRedirect(location="/orders").location == "/orders"
    assert ActionRefresh(target="orders-table").target == "orders-table"
    assert ActionRejected(errors={"reason": "not allowed"}).errors == {"reason": "not allowed"}
    with pytest.raises(ValueError, match="absolute"):
        ActionRedirect(location="orders")
    with pytest.raises(ValueError, match="requires errors"):
        ActionRejected(errors={})

    class EndpointInput(BaseModel):
        order_id: int

    class EndpointOutput(BaseModel):
        accepted: bool

    typed = EndpointDefinition(
        endpoint_id="typed",
        path="/typed",
        methods=(EndpointMethod.GET,),
        input_schema=EndpointInput,
        input_source="query",
        output_schema=EndpointOutput,
    )
    assert typed.output_schema is EndpointOutput
    assert typed.response_kind is EndpointResponseKind.JSON

    public = EndpointDefinition(
        endpoint_id="public", path="/public", methods=(EndpointMethod.GET,), access_policy="public"
    )
    assert public.access_policy is EndpointAccessPolicy.PUBLIC

    endpoint = EndpointDefinition(
        endpoint_id="download",
        path="/exports/orders",
        methods=(EndpointMethod.GET,),
        output_schema=None,
        response_kind=EndpointResponseKind.FILE,
        allow_response_escape_hatch=True,
    )
    assert endpoint.access_policy is EndpointAccessPolicy.PRIVATE
    assert endpoint.response_kind is EndpointResponseKind.FILE
    with pytest.raises(ValueError, match="escape hatch"):
        EndpointDefinition(
            endpoint_id="unsafe",
            path="/unsafe",
            methods=(EndpointMethod.GET,),
            response_kind=EndpointResponseKind.STREAM,
        )


def test_relationship_labels_validate_declared_fields_and_resolver_output() -> None:
    relationship = RelationshipDefinition(
        relationship_id="customer",
        target_resource_id="customers",
        label="Customer",
        kind=RelationshipKind.MANY_TO_ONE,
        cardinality=RelationshipCardinality.TO_ONE,
        record_label_field="name",
    )
    assert resolve_record_label(relationship, {"name": "Ada"}) == "Ada"

    custom = relationship.model_copy(
        update={"record_label_field": None, "record_label_resolver": lambda record: record["code"]}
    )
    assert resolve_record_label(custom, {"code": "C-1"}) == "C-1"
    invalid = custom.model_copy(update={"record_label_resolver": lambda _record: 3})
    with pytest.raises(TypeError, match="must return str"):
        resolve_record_label(invalid, {})
    with pytest.raises(ValueError, match="either"):
        RelationshipDefinition(
            relationship_id="bad_label",
            target_resource_id="customers",
            label="Bad",
            kind=RelationshipKind.MANY_TO_ONE,
            cardinality=RelationshipCardinality.TO_ONE,
            record_label_field="name",
            record_label_resolver=lambda _record: "name",
        )


def test_compilation_rejects_unknown_record_label_fields() -> None:
    relationship = RelationshipDefinition(
        relationship_id="customer",
        target_resource_id="customers",
        label="Customer",
        kind=RelationshipKind.MANY_TO_ONE,
        cardinality=RelationshipCardinality.TO_ONE,
        record_label_field="missing",
    )
    builder = ApplicationBuilder()
    builder.add_resource(
        _resource("orders", "/orders", relationships=(relationship,)), _DataSource()
    )
    builder.add_resource(_resource("customers", "/customers"), _DataSource())
    with pytest.raises(RakitError) as caught:
        compile_application(builder)
    assert caught.value.details["reason"] == "record_label_field_not_found"


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


def test_plan05_definition_routes_collide_and_only_global_namespaces_are_reserved() -> None:
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

    unrelated = ApplicationBuilder()
    unrelated.add_route(
        RouteDefinition(
            route_name="host.action",
            methods=("GET",),
            path="/internal/_actions-report",
            owner_id="host",
        )
    )
    assert compile_application(unrelated).routes[0].path == "/internal/_actions-report"

    reserved = ApplicationBuilder()
    reserved.add_route(
        RouteDefinition(
            route_name="host.auth",
            methods=("GET",),
            path="/auth/custom",
            owner_id="host",
        )
    )
    with pytest.raises(RakitError) as caught:
        compile_application(reserved)
    assert caught.value.code == ErrorCode.CONFIG_RESERVED_PATH

    system = ApplicationBuilder()
    system.add_route(
        RouteDefinition(
            route_name="host.system",
            methods=("GET",),
            path="/_system/health",
            owner_id="host",
        )
    )
    with pytest.raises(RakitError) as caught:
        compile_application(system)
    assert caught.value.code == ErrorCode.CONFIG_RESERVED_PATH


@pytest.mark.parametrize(
    ("kind", "path"),
    (
        ("page", "/orders/_actions/custom"),
        ("endpoint", "/orders/_actions/custom"),
        ("page", "/orders/{identity}/_actions/custom"),
        ("endpoint", "/orders/{identity}/_actions/custom"),
        ("page", "/orders/{identity}/_relationships/custom"),
        ("endpoint", "/orders/{identity}/_relationships/custom"),
    ),
)
def test_application_definitions_cannot_claim_resource_reserved_subpaths(
    kind: str, path: str
) -> None:
    builder = ApplicationBuilder()
    builder.add_resource(_resource("orders", "/orders"), _DataSource())
    if kind == "page":
        builder.add_page(PageDefinition(page_id="custom", path=path, label="Custom"))
    else:
        builder.add_endpoint(
            EndpointDefinition(endpoint_id="custom", path=path, methods=(EndpointMethod.GET,))
        )

    with pytest.raises(RakitError) as caught:
        compile_application(builder)
    assert caught.value.code == ErrorCode.CONFIG_RESERVED_PATH


def test_resource_reservation_is_scoped_and_generated_routes_remain_valid() -> None:
    relationship = RelationshipDefinition(
        relationship_id="customer",
        target_resource_id="customers",
        label="Customer",
        kind=RelationshipKind.MANY_TO_ONE,
        cardinality=RelationshipCardinality.TO_ONE,
    )
    builder = ApplicationBuilder()
    builder.add_resource(
        _resource("orders", "/orders", relationships=(relationship,)), _DataSource()
    )
    builder.add_resource(_resource("customers", "/customers"), _DataSource())
    builder.add_action(
        ActionDefinition(
            action_id="archive",
            label="Archive",
            scope=ActionScope.RESOURCE,
            resource_id="orders",
            executor=_noop_executor(),
        )
    )
    builder.add_action(
        ActionDefinition(
            action_id="approve",
            label="Approve",
            scope=ActionScope.RECORD,
            resource_id="orders",
            executor=_noop_executor(),
        )
    )
    builder.add_page(
        PageDefinition(page_id="internal", path="/internal/_actions-report", label="Internal")
    )
    builder.add_endpoint(
        EndpointDefinition(
            endpoint_id="summary",
            path="/reports/_relationships-summary",
            methods=(EndpointMethod.GET,),
        )
    )
    builder.add_route(
        RouteDefinition(
            route_name="host.custom.actions",
            methods=("GET",),
            path="/custom/_actions",
            owner_id="host",
        )
    )
    builder.add_route(
        RouteDefinition(
            route_name="host.custom.relationships",
            methods=("GET",),
            path="/custom/_relationships",
            owner_id="host",
        )
    )
    builder.add_route(
        RouteDefinition(
            route_name="host.orders.normal-child",
            methods=("GET",),
            path="/orders/foo/bar",
            owner_id="host",
        )
    )

    compiled = compile_application(builder)
    expected = {
        "/orders/_actions/archive",
        "/orders/{identity}/_actions/approve",
        "/orders/{identity}/_relationships/customer",
    }
    generated = [route for route in compiled.routes if route.path in expected]
    assert {route.path for route in generated} == expected
    assert all(not route.framework_owned for route in generated)


def test_bulk_defaults_are_safe() -> None:
    policy = BulkPolicy()
    assert policy.execution is BulkExecutionPolicy.ATOMIC
    assert policy.confirmation_threshold == 25
    assert policy.synchronous_maximum == 1000
    assert policy.require_concurrency_snapshot is True
    assert (
        BulkPolicy(confirmation_threshold=10, synchronous_maximum=500).confirmation_threshold == 10
    )
    with pytest.raises(ValueError):
        BulkPolicy(confirmation_threshold=26)
    with pytest.raises(ValueError):
        BulkPolicy(synchronous_maximum=1001)
    assert BulkPolicy(execution=BulkExecutionPolicy.BEST_EFFORT).synchronous_maximum == 1000
