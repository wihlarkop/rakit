"""Rakit Commerce: deterministic visual QA application for the default UI."""

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, cast

from rakit import (
    ActionDefinition,
    ActionScope,
    ActionSuccess,
    Admin,
    ChoiceFilter,
    DashboardDefinition,
    DataSourceCapabilities,
    DateRangeFilter,
    Filter,
    FilterChoice,
    FilterControl,
    FilterOperator,
    LauncherItem,
    ListWidgetItem,
    ListWidgetResult,
    PageDefinition,
    PagePagination,
    PageResult,
    PageSizePolicy,
    RelationshipCardinality,
    RelationshipDefinition,
    RelationshipKind,
    ResourceAdmin,
    ResourceFilter,
    ResourcePageResult,
    ResourcePaginationPolicy,
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
from rakit_core.actions import ActionContext, ActionPreview

from .data import CATEGORIES, CUSTOMERS, INVENTORY, ORDERS, PRODUCTS, TEAMS


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
    filter_fields = ("category", "status")
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

    async def touch(self, session_id: str) -> None:
        record = self._records.get(session_id)
        if record is None:
            return
        now = datetime.now(UTC)
        self._records[session_id] = SessionRecord(
            session_id=record.session_id,
            subject_id=record.subject_id,
            created_at=record.created_at,
            last_seen_at=now,
            idle_expires_at=now + timedelta(hours=1),
            absolute_expires_at=record.absolute_expires_at,
        )


class _MemoryIdempotencyStore:
    production_safe = False

    async def begin(self, token_hash: str, *, fingerprint: str) -> IdempotencyReservation:
        del token_hash, fingerprint
        return IdempotencyReservation(1, IdempotencyStatus.IN_PROGRESS)

    async def complete(self, reservation: IdempotencyReservation, receipt: OperationReceipt) -> None:
        del reservation, receipt

    async def release(self, reservation: IdempotencyReservation) -> None:
        del reservation

    async def fail_final(self, reservation: IdempotencyReservation) -> None:
        del reservation


async def revenue_widget(_context: Any) -> StatWidgetResult:
    return StatWidgetResult(value="$1.28M", trend_label="+12.4% vs last month", tone="positive")


async def orders_widget(_context: Any) -> StatWidgetResult:
    return StatWidgetResult(value="1,248", trend_label="+8.1% vs last month", tone="positive")


async def customers_widget(_context: Any) -> StatWidgetResult:
    return StatWidgetResult(value="328", trend_label="+24 this month", tone="positive")


async def open_returns_widget(_context: Any) -> StatWidgetResult:
    return StatWidgetResult(value="14", trend_label="3 need review", tone="warning")


async def attention_widget(_context: Any) -> ListWidgetResult:
    return ListWidgetResult(
        items=(
            ListWidgetItem(title="Inventory below threshold", meta="3 SKUs · Fulfilment"),
            ListWidgetItem(title="Orders pending manual review", meta="7 orders · Operations"),
            ListWidgetItem(title="Catalog entries in review", meta="2 products · Catalog"),
        )
    )


async def recent_orders_widget(_context: Any) -> TableWidgetResult:
    return TableWidgetResult(
        columns=("Order", "Customer", "Status", "Total"),
        rows=tuple(
            (str(order["id"]), str(order["customer"]), str(order["status"]), str(order["total"]))
            for order in ORDERS[:5]
        ),
    )


async def broken_widget(_context: Any) -> WidgetErrorResult:
    return WidgetErrorResult(
        title="Shipping sync unavailable",
        message="Carrier data could not be loaded. Other dashboard widgets remain available.",
    )


DASHBOARD = DashboardDefinition(
    dashboard_id="commerce_operations",
    title="Commerce operations",
    description="Monitor revenue, fulfilment, inventory, and customer activity.",
    launchers=(
        LauncherItem(resource_id="orders", label="Orders", description="Review and manage orders."),
        LauncherItem(resource_id="customers", label="Customers", description="Manage customer accounts."),
        LauncherItem(resource_id="products", label="Products", description="Maintain the catalog."),
        LauncherItem(resource_id="inventory", label="Inventory", description="Track stock health."),
    ),
    widgets=(
        WidgetDefinition(
            widget_id="revenue",
            title="Revenue",
            resolver=revenue_widget,
            layout=WidgetLayout(row=1, column=1),
        ),
        WidgetDefinition(
            widget_id="orders",
            title="Orders",
            resolver=orders_widget,
            layout=WidgetLayout(row=1, column=2),
        ),
        WidgetDefinition(
            widget_id="customers",
            title="Customers",
            resolver=customers_widget,
            layout=WidgetLayout(row=1, column=3),
        ),
        WidgetDefinition(
            widget_id="returns",
            title="Open returns",
            resolver=open_returns_widget,
            layout=WidgetLayout(row=1, column=4),
        ),
        WidgetDefinition(
            widget_id="attention",
            title="Needs attention",
            resolver=attention_widget,
            layout=WidgetLayout(row=2, column=1, column_span=2),
        ),
        WidgetDefinition(
            widget_id="recent_orders",
            title="Recent orders",
            resolver=recent_orders_widget,
            layout=WidgetLayout(row=2, column=3, column_span=2),
        ),
        WidgetDefinition(
            widget_id="shipping_sync",
            title="Shipping sync",
            resolver=broken_widget,
            loading=WidgetLoadingMode.LAZY,
            layout=WidgetLayout(row=3, column=1, column_span=2),
        ),
    ),
)


admin = Admin(
    admin_id="ui_showcase",
    title="Rakit Commerce",
    debug=True,
    secret_key=SecretValue("ui-showcase-secret-key-material"),
    auth_backend=DemoAuthBackend(),
    session_store=DemoSessionStore(),
    operation_idempotency_store=_MemoryIdempotencyStore(),
)
admin.register(CustomersAdmin)
admin.register(ProductsAdmin)
admin.register(OrdersAdmin)
admin.register(CategoriesAdmin)
admin.register(InventoryAdmin)
admin.register(TeamsAdmin)
admin.register_page(PageDefinition(page_id="ui_lab", path="/ui-lab", title="UI Lab"))
admin.register_dashboard(DASHBOARD)
