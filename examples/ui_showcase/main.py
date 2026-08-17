"""Rakit Commerce: deterministic visual QA application for the default UI."""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from rakit import (
    ActionDefinition,
    ActionScope,
    ActionSuccess,
    Admin,
    DashboardDefinition,
    PageDefinition,
    PageResult,
    RelationshipCardinality,
    RelationshipDefinition,
    RelationshipKind,
    ResourceAdmin,
    SecretValue,
    StatWidgetResult,
    TableWidgetResult,
    WidgetDefinition,
    WidgetLayout,
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
    return False


class _MemoryDataSource:
    capabilities = type("Capabilities", (), {"read": True})()

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

    async def list(self, query: Any) -> _Page:
        items = self._filtered(query)
        start = query.pagination.offset
        end = start + query.pagination.per_page
        return _Page(
            items=tuple(items[start:end]),
            page=query.pagination.page,
            per_page=query.pagination.per_page,
            has_previous=query.pagination.page > 1,
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


class RefundOrder:
    async def execute(self, context: ActionContext) -> ActionSuccess[dict[str, object]]:
        record = context.record
        if isinstance(record, dict):
            record["status"] = "Refunded"
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
    filter_fields = ("customer", "status")
    search_fields = ("id", "customer")
    sort_fields = ("id", "customer", "status", "created")
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
    filter_fields = ("status",)
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
admin.register_dashboard(
    DashboardDefinition(
        dashboard_id="main",
        title="Commerce operations",
        widgets=("pending_orders", "recent_orders"),
    )
)


def ui_lab_page(_context: object) -> PageResult[dict[str, object]]:
    return PageResult(
        payload={
            "purpose": "Deterministic visual QA for the default Rakit UI",
            "order_count": len(ORDERS),
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

app = admin.asgi()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8000)
