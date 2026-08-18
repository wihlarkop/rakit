"""Rakit Commerce: deterministic visual QA application for the default UI."""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, cast

from rakit import (
    ActionDefinition,
    ActionIntent,
    ActionPresentation,
    ActionScope,
    ActionSuccess,
    Admin,
    BulkExecutionPolicy,
    BulkPolicy,
    ChoiceFilter,
    DashboardDefinition,
    DataSourceCapabilities,
    DateRangeFilter,
    Filter,
    FilterChoice,
    FilterControl,
    FilterGroupPresentation,
    FilterOperator,
    FilterPanelPresentation,
    LauncherItem,
    ListWidgetItem,
    ListWidgetResult,
    PageDefinition,
    PagePagination,
    PageResult,
    PageSizePolicy,
    PageWebPresentation,
    RelationshipCardinality,
    RelationshipDefinition,
    RelationshipKind,
    ResourceAdmin,
    ResourceFilter,
    ResourcePageResult,
    ResourcePaginationPolicy,
    ResourceWebPresentation,
    SecretValue,
    StatWidgetResult,
    TableWidgetResult,
    TextFilter,
    WidgetDefinition,
    WidgetErrorResult,
    WidgetLayout,
    WidgetLoadingMode,
)
from rakit.core import (
    IdempotencyReservation,
    IdempotencyStatus,
    OperationReceipt,
    Principal,
    SessionRecord,
    TransactionPolicy,
)
from rakit_core.actions import ActionAvailabilityDecision, ActionContext, ActionPreview
from rakit_core.fields import FieldDefinition
from rakit_core.forms import FormSchema

from .data import CATEGORIES, CUSTOMERS, INVENTORY, ORDERS, PRODUCTS, TEAMS


@dataclass(frozen=True)
class _Page:
    items: tuple[dict[str, object], ...]
    page: int
    per_page: int
    has_previous: bool
    has_next: bool
    total_count: int | None


def _matches(item: dict[str, object], filter_: Any) -> bool:
    actual = item.get(filter_.field)
    operator = filter_.operator.value
    expected = filter_.value
    if operator == "eq":
        return str(actual) == str(expected)
    if operator == "neq":
        return str(actual) != str(expected)
    if operator == "contains":
        return str(expected).casefold() in str(actual).casefold()
    if operator == "in":
        return str(actual) in {str(value) for value in expected}
    if operator == "is_null":
        return (actual is None) is bool(expected)
    if operator == "lt":
        return str(actual) < str(expected)
    if operator == "lte":
        return str(actual) <= str(expected)
    if operator == "gt":
        return str(actual) > str(expected)
    if operator == "gte":
        return str(actual) >= str(expected)
    return False


class _MemoryDataSource:
    capabilities = DataSourceCapabilities(read=True)

    def __init__(
        self,
        items: tuple[dict[str, object], ...],
        fields: tuple[str, ...],
    ) -> None:
        self._items = items
        self.fields = fields
        self.identity_fields = ("id",)

    def _filtered(self, query: Any) -> list[dict[str, object]]:
        items = list(self._items)
        for filter_ in query.filters:
            items = [item for item in items if _matches(item, filter_)]
        if query.search:
            needle = query.search.casefold()
            items = [
                item
                for item in items
                if any(needle in str(value).casefold() for value in item.values())
            ]
        for sort in reversed(query.sorting):
            items.sort(
                key=lambda item: str(item.get(sort.field, "")),
                reverse=sort.direction.value == "desc",
            )
        return items

    async def list(self, query: Any) -> ResourcePageResult[dict[str, object]]:
        pagination = query.pagination
        if not isinstance(pagination, PagePagination):
            raise ValueError("UI showcase memory data source supports page pagination only")
        items = self._filtered(query)
        start = pagination.offset
        end = start + pagination.per_page
        return ResourcePageResult(
            items=tuple(items[start:end]),
            page=pagination.page,
            per_page=pagination.per_page,
            has_previous=pagination.page > 1,
            has_next=end < len(items),
            total_count=len(items) if query.count_policy.value == "exact" else None,
        )

    async def count(self, query: Any) -> int:
        return len(self._filtered(query))

    async def detail(self, identity: Any) -> dict[str, object] | None:
        wanted = str(identity.values["id"])
        return next((item for item in self._items if str(item["id"]) == wanted), None)

    def validate_relationship(
        self,
        definition: RelationshipDefinition,
        target_data_source: object,
        association_target_data_source: object | None,
    ) -> None:
        del definition, target_data_source, association_target_data_source


class StockLevelFilter(ResourceFilter):
    """Semantic showcase filter resolved without datasource-specific query objects."""

    def parse_value(self, *, operator: FilterOperator, raw_value: object) -> object:
        if operator is not FilterOperator.EQ or not isinstance(raw_value, str):
            raise ValueError("Stock-level filter accepts one named choice")
        if raw_value not in {choice.value for choice in self.choices}:
            raise ValueError("Stock-level filter choice is not allowed")
        return raw_value

    def resolve_predicates(
        self,
        *,
        operator: FilterOperator,
        value: object,
    ) -> tuple[Filter, ...]:
        if operator is not FilterOperator.EQ or not isinstance(value, str):
            raise ValueError("Stock-level filter selection is invalid")
        if value == "attention":
            return (
                Filter(
                    field="status",
                    operator=FilterOperator.IN,
                    value=("Low stock", "Out of stock"),
                ),
            )
        if value == "out":
            return (
                Filter(
                    field="status",
                    operator=FilterOperator.EQ,
                    value="Out of stock",
                ),
            )
        raise ValueError("Stock-level filter choice is not allowed")


class RefundOrder:
    async def execute(self, context: ActionContext) -> ActionSuccess[dict[str, object]]:
        record = context.record
        if isinstance(record, dict):
            cast(dict[str, object], record)["status"] = "Refunded"
        return ActionSuccess(payload={"status": "Refunded"}, message="Order refunded")


def refund_preview(_context: ActionContext) -> ActionPreview:
    return ActionPreview(
        title="Refund order",
        description="Review this refund before applying it to the selected order.",
        impact="The order status will change to Refunded in this development-only showcase.",
    )


class ShowcaseAction:
    def __init__(self, message: str) -> None:
        self.message = message

    async def execute(self, context: ActionContext) -> ActionSuccess[dict[str, object]]:
        return ActionSuccess(
            payload={"action": str(context.definition.action_id)},
            message=self.message,
        )


class AddOrderNote:
    async def execute(self, context: ActionContext) -> ActionSuccess[dict[str, object]]:
        note = context.values["note"] if context.values is not None else ""
        return ActionSuccess(
            payload={"note": note},
            message="Operator note accepted for the UI showcase",
        )


ORDER_NOTE_FORM = FormSchema(
    fields=(
        FieldDefinition(
            field_id="note",
            python_type=str,
            label="Operator note",
            required=True,
            description="Required so the action form has a deterministic validation state.",
        ),
    )
)


def warehouse_sync_disabled(_context: ActionContext) -> ActionAvailabilityDecision:
    return ActionAvailabilityDecision.disabled("Warehouse sync is currently unavailable.")


def hidden_action(_context: ActionContext) -> ActionAvailabilityDecision:
    return ActionAvailabilityDecision.hidden()


class CustomersAdmin(ResourceAdmin):
    resource_id = "customers"
    path = "/customers"
    label = "Customers"
    singular_label = "Customer"
    data_source = _MemoryDataSource(
        CUSTOMERS,
        ("id", "name", "segment", "status", "owner", "email"),
    )
    list_fields = ("id", "name", "segment", "status", "owner", "email")
    detail_fields = ("id", "name", "segment", "status", "owner", "email")
    filter_fields = ("segment", "status", "owner")
    search_fields = ("id", "name", "email")
    sort_fields = ("id", "name", "segment", "status")


class ProductsAdmin(ResourceAdmin):
    resource_id = "products"
    path = "/products"
    label = "Products"
    singular_label = "Product"
    data_source = _MemoryDataSource(
        PRODUCTS,
        ("id", "name", "category", "sku", "status", "price"),
    )
    list_fields = ("id", "name", "category", "sku", "status", "price")
    detail_fields = ("id", "name", "category", "sku", "status", "price")
    filters = (
        ChoiceFilter(
            filter_id="category",
            label="Category",
            field="category",
            choices=(
                FilterChoice(value="Workspace", label="Workspace"),
                FilterChoice(value="Input devices", label="Input devices"),
                FilterChoice(value="Displays", label="Displays"),
                FilterChoice(value="Accessories", label="Accessories"),
                FilterChoice(value="Audio & conferencing", label="Audio & conferencing"),
                FilterChoice(
                    value="Ergonomic workspace accessories",
                    label="Ergonomic workspace accessories",
                ),
                FilterChoice(value="Power and charging", label="Power and charging"),
                FilterChoice(value="Networking", label="Networking"),
                FilterChoice(value="Storage", label="Storage"),
                FilterChoice(value="Travel workspace", label="Travel workspace"),
            ),
        ),
        ChoiceFilter(
            filter_id="status",
            label="Status",
            field="status",
            choices=(
                FilterChoice(value="Published", label="Published"),
                FilterChoice(value="Draft", label="Draft"),
                FilterChoice(value="Review", label="Review"),
                FilterChoice(value="Archived", label="Archived"),
            ),
        ),
        TextFilter(filter_id="name", label="Name", field="name"),
        TextFilter(filter_id="sku", label="SKU", field="sku"),
        TextFilter(filter_id="price", label="Price label", field="price"),
    )
    filter_fields = ()
    search_fields = ("id", "name", "sku")
    sort_fields = ("id", "name", "category", "status")


class OrdersAdmin(ResourceAdmin):
    resource_id = "orders"
    path = "/orders"
    label = "Orders"
    singular_label = "Order"
    data_source = _MemoryDataSource(
        ORDERS,
        ("id", "customer", "status", "items", "total", "created"),
    )
    list_fields = ("id", "customer", "status", "items", "total", "created")
    detail_fields = ("id", "customer", "status", "items", "total", "created")
    filters = (
        TextFilter(
            filter_id="customer",
            label="Customer",
            field="customer",
            operators=(FilterOperator.CONTAINS, FilterOperator.EQ),
        ),
        ChoiceFilter(
            filter_id="status",
            label="Status",
            field="status",
            choices=(
                FilterChoice(value="Paid", label="Paid"),
                FilterChoice(value="Pending review", label="Pending review"),
                FilterChoice(value="Processing", label="Processing"),
                FilterChoice(value="Fulfilled", label="Fulfilled"),
                FilterChoice(value="Refunded", label="Refunded"),
                FilterChoice(value="Cancelled", label="Cancelled"),
            ),
        ),
        DateRangeFilter(
            filter_id="created",
            label="Created",
            field="created",
        ),
    )
    filter_fields = ()
    search_fields = ("id", "customer")
    sort_fields = ("id", "customer", "status", "created")
    pagination = ResourcePaginationPolicy(size=PageSizePolicy(default=20, allowed=(20, 40, 80)))
    relationships = (
        RelationshipDefinition(
            relationship_id="customer",
            target_resource_id="customers",
            label="Customer",
            kind=RelationshipKind.MANY_TO_ONE,
            cardinality=RelationshipCardinality.TO_ONE,
            nullable=True,
            record_label_field="name",
        ),
        RelationshipDefinition(
            relationship_id="products",
            target_resource_id="products",
            label="Products",
            kind=RelationshipKind.MANY_TO_MANY,
            cardinality=RelationshipCardinality.TO_MANY,
            record_label_field="name",
        ),
    )
    actions = (
        ActionDefinition(
            action_id="export_orders",
            label="Export orders",
            scope=ActionScope.RESOURCE,
            resource_id="orders",
            description="Primary resource action for UI-06A hierarchy QA.",
            executor=ShowcaseAction("Order export queued in the UI showcase"),
        ),
        ActionDefinition(
            action_id="warehouse_sync",
            label="Sync warehouse",
            scope=ActionScope.RESOURCE,
            resource_id="orders",
            description="Deterministic disabled resource action.",
            availability=warehouse_sync_disabled,
            executor=ShowcaseAction("Warehouse sync completed"),
        ),
        ActionDefinition(
            action_id="internal_reindex",
            label="Internal reindex",
            scope=ActionScope.RESOURCE,
            resource_id="orders",
            availability=hidden_action,
            executor=ShowcaseAction("Internal reindex completed"),
        ),
        ActionDefinition(
            action_id="add_order_note",
            label="Add operator note",
            scope=ActionScope.RECORD,
            resource_id="orders",
            description="Typed record action with required input.",
            input_schema=ORDER_NOTE_FORM,
            executor=AddOrderNote(),
            needs_form=True,
        ),
        ActionDefinition(
            action_id="hidden_risk_diagnostics",
            label="Risk diagnostics",
            scope=ActionScope.RECORD,
            resource_id="orders",
            availability=hidden_action,
            executor=ShowcaseAction("Diagnostics complete"),
        ),
        ActionDefinition(
            action_id="refund_order",
            label="Refund order",
            scope=ActionScope.RECORD,
            resource_id="orders",
            description="Refund the selected order.",
            preview=refund_preview,
            executor=RefundOrder(),
            needs_preview=True,
            needs_confirmation=True,
            mutating=True,
            transaction_policy=TransactionPolicy.DISABLED,
        ),
        ActionDefinition(
            action_id="bulk_mark_reviewed",
            label="Mark reviewed",
            scope=ActionScope.BULK,
            resource_id="orders",
            description="Safe bulk action for no-JavaScript selection QA.",
            executor=ShowcaseAction("Selected orders marked reviewed in the UI showcase"),
            bulk_policy=BulkPolicy(require_concurrency_snapshot=False),
        ),
        ActionDefinition(
            action_id="bulk_cancel_orders",
            label="Cancel orders",
            scope=ActionScope.BULK,
            resource_id="orders",
            description="Danger bulk action with confirmation review.",
            preview=lambda _context: ActionPreview(
                title="Cancel selected orders",
                description="Review the selected orders before cancellation.",
                impact="The selected orders will be cancelled in this development-only showcase.",
            ),
            executor=ShowcaseAction("Selected orders cancelled in the UI showcase"),
            needs_preview=True,
            needs_confirmation=True,
            bulk_policy=BulkPolicy(
                execution=BulkExecutionPolicy.BEST_EFFORT,
                require_concurrency_snapshot=False,
            ),
        ),
        ActionDefinition(
            action_id="bulk_warehouse_sync",
            label="Sync selected with warehouse",
            scope=ActionScope.BULK,
            resource_id="orders",
            availability=warehouse_sync_disabled,
            executor=ShowcaseAction("Selected orders synchronized"),
            bulk_policy=BulkPolicy(require_concurrency_snapshot=False),
        ),
        ActionDefinition(
            action_id="bulk_hidden_hold",
            label="Internal bulk hold",
            scope=ActionScope.BULK,
            resource_id="orders",
            availability=hidden_action,
            executor=ShowcaseAction("Selected orders held"),
            bulk_policy=BulkPolicy(require_concurrency_snapshot=False),
        ),
    )


class CategoriesAdmin(ResourceAdmin):
    resource_id = "categories"
    path = "/categories"
    label = "Categories"
    singular_label = "Category"
    data_source = _MemoryDataSource(
        CATEGORIES,
        ("id", "name", "status", "products"),
    )
    list_fields = ("id", "name", "status", "products")
    detail_fields = ("id", "name", "status", "products")
    filter_fields = ("status",)
    search_fields = ("id", "name")
    sort_fields = ("id", "name", "status", "products")


class InventoryAdmin(ResourceAdmin):
    resource_id = "inventory"
    path = "/inventory"
    label = "Inventory"
    singular_label = "Inventory item"
    data_source = _MemoryDataSource(
        INVENTORY,
        ("id", "sku", "product", "on_hand", "reorder_at", "status"),
    )
    list_fields = ("id", "sku", "product", "on_hand", "reorder_at", "status")
    detail_fields = ("id", "sku", "product", "on_hand", "reorder_at", "status")
    filters = (
        StockLevelFilter(
            filter_id="stock_level",
            label="Stock level",
            predicate_fields=("status",),
            control=FilterControl.CHOICE,
            operators=(FilterOperator.EQ,),
            choices=(
                FilterChoice(value="attention", label="Needs attention"),
                FilterChoice(value="out", label="Out of stock"),
            ),
        ),
    )
    filter_fields = ()
    search_fields = ("id", "sku", "product")
    sort_fields = ("id", "sku", "product", "on_hand", "status")


class TeamsAdmin(ResourceAdmin):
    resource_id = "teams"
    path = "/teams"
    label = "Teams"
    singular_label = "Team"
    data_source = _MemoryDataSource(
        TEAMS,
        ("id", "name", "lead", "members", "status"),
    )
    list_fields = ("id", "name", "lead", "members", "status")
    detail_fields = ("id", "name", "lead", "members", "status")
    filter_fields = ("status", "lead")
    search_fields = ("id", "name", "lead")
    sort_fields = ("id", "name", "lead", "members", "status")


class DemoAuthBackend:
    async def authenticate(self, identifier: str, password: str) -> Principal | None:
        if (identifier.strip().lower(), password) != ("operator@example.com", "demo-password"):
            return None
        return self._principal()

    async def resolve_principal(self, subject_id: str) -> Principal | None:
        return self._principal() if subject_id == "ui-showcase-operator" else None

    @staticmethod
    def _principal() -> Principal:
        return Principal(
            subject_id="ui-showcase-operator",
            authenticated=True,
            display_name="Commerce Operator",
            is_superuser=True,
        )


class DemoSessionStore:
    production_safe = False

    def __init__(self) -> None:
        self._records: dict[str, SessionRecord] = {}
        self._tokens: dict[str, str] = {}
        self._counter = 0

    async def create(self, principal: Principal) -> tuple[str, SessionRecord]:
        assert principal.subject_id is not None
        return self._new_session(principal.subject_id)

    async def resolve(self, raw_token: str) -> SessionRecord | None:
        session_id = self._tokens.get(raw_token)
        if session_id is None:
            return None
        record = self._records.get(session_id)
        if record is None or record.absolute_expires_at <= datetime.now(UTC):
            return None
        return record

    async def rotate(self, session_id: str) -> tuple[str, SessionRecord]:
        previous = self._records.pop(session_id)
        for token, stored_id in tuple(self._tokens.items()):
            if stored_id == session_id:
                self._tokens.pop(token, None)
        return self._new_session(previous.subject_id)

    async def revoke(self, session_id: str) -> None:
        self._records.pop(session_id, None)
        self._tokens = {
            token: stored_id for token, stored_id in self._tokens.items() if stored_id != session_id
        }

    def _new_session(self, subject_id: str) -> tuple[str, SessionRecord]:
        self._counter += 1
        now = datetime.now(UTC)
        session_id = f"ui-showcase-session-{self._counter}"
        raw_token = f"ui-showcase-token-{self._counter}"
        record = SessionRecord(
            session_id=session_id,
            subject_id=subject_id,
            created_at=now,
            last_seen_at=now,
            idle_expires_at=now + timedelta(hours=1),
            absolute_expires_at=now + timedelta(hours=8),
        )
        self._records[session_id] = record
        self._tokens[raw_token] = session_id
        return raw_token, record


class DemoIdempotencyStore:
    production_safe = False

    async def begin(self, token_hash: str, *, fingerprint: str) -> IdempotencyReservation:
        del token_hash, fingerprint
        return IdempotencyReservation(1, IdempotencyStatus.IN_PROGRESS)

    async def complete(
        self,
        reservation: IdempotencyReservation,
        receipt: OperationReceipt,
    ) -> None:
        del reservation, receipt

    async def release(self, reservation: IdempotencyReservation) -> None:
        del reservation

    async def fail_final(self, reservation: IdempotencyReservation) -> None:
        del reservation


admin = Admin(
    admin_id="ui_showcase",
    title="Rakit Commerce",
    debug=True,
    secret_key=SecretValue("development-only-ui-showcase-key"),
    template_dirs=(Path(__file__).parent / "templates",),
    auth_backend=DemoAuthBackend(),
    session_store=DemoSessionStore(),
    operation_idempotency_store=DemoIdempotencyStore(),
)
for resource_admin in (
    CustomersAdmin,
    ProductsAdmin,
    OrdersAdmin,
    CategoriesAdmin,
    InventoryAdmin,
    TeamsAdmin,
):
    if resource_admin is ProductsAdmin:
        admin.register(
            resource_admin,
            web=ResourceWebPresentation(
                filters=FilterPanelPresentation(
                    groups={
                        "category": FilterGroupPresentation(choice_preview_count=5),
                    }
                )
            ),
        )
    elif resource_admin is OrdersAdmin:
        admin.register(
            resource_admin,
            web=ResourceWebPresentation(
                actions={
                    "export_orders": ActionPresentation(intent=ActionIntent.PRIMARY),
                    "refund_order": ActionPresentation(intent=ActionIntent.DANGER),
                    "bulk_mark_reviewed": ActionPresentation(intent=ActionIntent.PRIMARY),
                    "bulk_cancel_orders": ActionPresentation(intent=ActionIntent.DANGER),
                }
            ),
        )
    else:
        admin.register(resource_admin)


async def pending_orders(_context: object) -> StatWidgetResult:
    count = sum(1 for order in ORDERS if order["status"] == "Pending review")
    return StatWidgetResult(
        label="Pending review",
        value=count,
        description="Orders waiting for an operator decision.",
    )


async def recent_orders(_context: object) -> TableWidgetResult:
    return TableWidgetResult(
        label="Recent orders",
        columns=("Order", "Customer", "Status", "Total"),
        rows=tuple(
            (order["id"], order["customer"], order["status"], order["total"])
            for order in ORDERS[:5]
        ),
    )


async def low_inventory(_context: object) -> ListWidgetResult:
    low_items = tuple(item for item in INVENTORY if item["status"] in {"Low stock", "Out of stock"})
    return ListWidgetResult(
        label="Inventory attention",
        items=tuple(
            ListWidgetItem(
                label=str(item["product"]),
                value=f"{item['on_hand']} on hand",
                href="/inventory",
            )
            for item in low_items
        ),
        empty_message="No inventory items need attention.",
    )


async def recent_activity(_context: object) -> ListWidgetResult:
    return ListWidgetResult(
        label="Recent activity",
        items=tuple(
            ListWidgetItem(
                label=f"{order['id']} · {order['customer']}",
                value=str(order["status"]),
                href="/orders",
            )
            for order in ORDERS[:4]
        ),
    )


async def returns_queue(_context: object) -> ListWidgetResult:
    return ListWidgetResult(
        label="Returns queue",
        items=(),
        empty_message="No returns need review right now.",
    )


async def warehouse_sync(_context: object) -> WidgetErrorResult:
    return WidgetErrorResult(
        label="Warehouse sync",
        message="The warehouse sync is unavailable in this deterministic demo.",
    )


admin.register_widget(
    WidgetDefinition(
        widget_id="pending_orders",
        label="Pending review",
        loader=pending_orders,
        layout=WidgetLayout(size="small", priority=10),
    )
)
admin.register_widget(
    WidgetDefinition(
        widget_id="recent_orders",
        label="Recent orders",
        loader=recent_orders,
        layout=WidgetLayout(size="large", priority=20),
    )
)
admin.register_widget(
    WidgetDefinition(
        widget_id="low_inventory",
        label="Inventory attention",
        loader=low_inventory,
        layout=WidgetLayout(size="medium", priority=30),
    )
)
admin.register_widget(
    WidgetDefinition(
        widget_id="recent_activity",
        label="Recent activity",
        loader=recent_activity,
        loading=WidgetLoadingMode.LAZY,
        layout=WidgetLayout(size="medium", priority=40),
    )
)
admin.register_widget(
    WidgetDefinition(
        widget_id="returns_queue",
        label="Returns queue",
        loader=returns_queue,
        layout=WidgetLayout(size="medium", priority=50),
    )
)
admin.register_widget(
    WidgetDefinition(
        widget_id="warehouse_sync",
        label="Warehouse sync",
        loader=warehouse_sync,
        layout=WidgetLayout(size="medium", priority=60),
    )
)
admin.register_dashboard(
    DashboardDefinition(
        dashboard_id="main",
        title="Commerce operations",
        widgets=(
            "pending_orders",
            "recent_orders",
            "low_inventory",
            "recent_activity",
            "returns_queue",
            "warehouse_sync",
        ),
        launchers=(
            LauncherItem(
                launcher_id="orders",
                label="Orders",
                path="/orders",
                description="Review incoming orders, fulfilment state, and customer activity.",
            ),
            LauncherItem(
                launcher_id="inventory",
                label="Inventory",
                path="/inventory",
                description="Monitor stock levels and replenish items that need attention.",
            ),
            LauncherItem(
                launcher_id="products",
                label="Products",
                path="/products",
                description="Browse the product catalogue and publication state.",
            ),
            LauncherItem(
                launcher_id="operations",
                label="Action states",
                path="/operations",
                description="Exercise page action hierarchy, disabled state, and hidden state.",
            ),
            LauncherItem(
                launcher_id="ui_lab",
                label="UI Lab",
                path="/ui-lab",
                description="Inspect default Rakit component states for deterministic visual QA.",
            ),
        ),
    )
)


def ui_lab_page(_context: object) -> PageResult[dict[str, object]]:
    return PageResult(
        payload={
            "purpose": "Deterministic visual QA for the default Rakit UI",
            "order_count": len(ORDERS),
        }
    )


def operations_page(_context: object) -> PageResult[dict[str, object]]:
    return PageResult(
        payload={
            "purpose": "UI-06A page action states",
            "expected": "Primary direct, disabled in More, hidden omitted",
        }
    )


admin.register_page(
    PageDefinition(
        page_id="ui_lab",
        path="/ui-lab",
        label="UI Lab",
        handler=ui_lab_page,
        template="ui_lab.html",
    )
)
admin.register_page(
    PageDefinition(
        page_id="operations",
        path="/operations",
        label="Action states",
        handler=operations_page,
    ),
    actions=(
        ActionDefinition(
            action_id="refresh_operations",
            label="Refresh operations",
            scope=ActionScope.PAGE,
            page_id="operations",
            executor=ShowcaseAction("Operations refreshed"),
        ),
        ActionDefinition(
            action_id="page_warehouse_sync",
            label="Sync warehouse",
            scope=ActionScope.PAGE,
            page_id="operations",
            availability=warehouse_sync_disabled,
            executor=ShowcaseAction("Warehouse synchronized"),
        ),
        ActionDefinition(
            action_id="page_hidden_diagnostics",
            label="Internal diagnostics",
            scope=ActionScope.PAGE,
            page_id="operations",
            availability=hidden_action,
            executor=ShowcaseAction("Diagnostics completed"),
        ),
    ),
    web=PageWebPresentation(
        actions={
            "refresh_operations": ActionPresentation(intent=ActionIntent.PRIMARY),
        }
    ),
)

app = admin.asgi()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8000)
