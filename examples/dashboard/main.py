from dataclasses import dataclass
from typing import Any

from rakit import (
    Admin,
    DashboardDefinition,
    ListWidgetItem,
    ListWidgetResult,
    ResourceAdmin,
    StatWidgetResult,
    TableWidgetResult,
    TextWidgetResult,
    WidgetDefinition,
    WidgetLayout,
    WidgetLoadingMode,
)

_ORDERS: tuple[dict[str, object], ...] = (
    {
        "id": "ORD-1042",
        "customer": "Northstar Labs",
        "status": "Pending review",
        "total": "$1,840",
    },
    {
        "id": "ORD-1041",
        "customer": "Acme Studio",
        "status": "Approved",
        "total": "$920",
    },
    {
        "id": "ORD-1040",
        "customer": "Vertex Supply",
        "status": "Processing",
        "total": "$2,310",
    },
    {
        "id": "ORD-1039",
        "customer": "Juniper Works",
        "status": "Fulfilled",
        "total": "$640",
    },
)

_CUSTOMERS: tuple[dict[str, object], ...] = (
    {
        "id": "CUS-201",
        "name": "Northstar Labs",
        "plan": "Scale",
        "status": "Active",
    },
    {
        "id": "CUS-202",
        "name": "Acme Studio",
        "plan": "Team",
        "status": "Active",
    },
    {
        "id": "CUS-203",
        "name": "Vertex Supply",
        "plan": "Scale",
        "status": "Active",
    },
    {
        "id": "CUS-204",
        "name": "Juniper Works",
        "plan": "Team",
        "status": "Review",
    },
)

_ACTIVITY: tuple[dict[str, object], ...] = (
    {
        "id": "EVT-401",
        "time": "09:42",
        "event": "Order ORD-1041 approved",
        "actor": "Maya Chen",
    },
    {
        "id": "EVT-400",
        "time": "09:18",
        "event": "Customer CUS-204 moved to review",
        "actor": "System",
    },
    {
        "id": "EVT-399",
        "time": "08:55",
        "event": "Export batch completed",
        "actor": "Worker 03",
    },
    {
        "id": "EVT-398",
        "time": "08:31",
        "event": "Order ORD-1042 submitted for review",
        "actor": "Owen Park",
    },
)

_RUNBOOK: tuple[dict[str, object], ...] = (
    {
        "id": "RUN-01",
        "topic": "Order review",
        "guidance": "Review payment state before approving or escalating a pending order.",
    },
    {
        "id": "RUN-02",
        "topic": "Export queue",
        "guidance": "Check failed exports before retrying and escalate repeated failures.",
    },
    {
        "id": "RUN-03",
        "topic": "Customer review",
        "guidance": "Confirm account ownership and recent activity before clearing a review hold.",
    },
)


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
        wanted = identity.values["id"]
        return next((item for item in self._items if item["id"] == wanted), None)


class OrdersAdmin(ResourceAdmin):
    resource_id = "orders"
    path = "/orders"
    label = "Orders"
    singular_label = "Order"
    data_source = _MemoryDataSource(_ORDERS, ("id", "customer", "status", "total"))
    list_fields = ("id", "customer", "status", "total")
    detail_fields = ("id", "customer", "status", "total")
    filter_fields = ("customer", "status")
    search_fields = ("id", "customer")
    sort_fields = ("id", "customer", "status")


class CustomersAdmin(ResourceAdmin):
    resource_id = "customers"
    path = "/customers"
    label = "Customers"
    singular_label = "Customer"
    data_source = _MemoryDataSource(_CUSTOMERS, ("id", "name", "plan", "status"))
    list_fields = ("id", "name", "plan", "status")
    detail_fields = ("id", "name", "plan", "status")
    filter_fields = ("plan", "status")
    search_fields = ("id", "name")
    sort_fields = ("id", "name", "plan", "status")


class ActivityAdmin(ResourceAdmin):
    resource_id = "activity"
    path = "/activity"
    label = "Recent operational activity"
    singular_label = "Activity event"
    data_source = _MemoryDataSource(_ACTIVITY, ("id", "time", "event", "actor"))
    list_fields = ("time", "event", "actor")
    detail_fields = ("id", "time", "event", "actor")
    filter_fields = ("actor",)
    search_fields = ("event", "actor")
    sort_fields = ("time", "actor")


class RunbookAdmin(ResourceAdmin):
    resource_id = "runbook"
    path = "/runbook"
    label = "Operations runbook"
    singular_label = "Runbook entry"
    data_source = _MemoryDataSource(_RUNBOOK, ("id", "topic", "guidance"))
    list_fields = ("topic", "guidance")
    detail_fields = ("id", "topic", "guidance")
    search_fields = ("topic", "guidance")
    sort_fields = ("topic",)


admin = Admin(title="Operations", debug=True)
admin.register(OrdersAdmin)
admin.register(CustomersAdmin)
admin.register(ActivityAdmin)
admin.register(RunbookAdmin)


async def pending_orders(_context):
    return StatWidgetResult(
        label="Pending orders",
        value=12,
        description="Orders waiting for review.",
    )


async def operations_note(_context):
    return TextWidgetResult(
        label="Operations note",
        text="Review pending orders before 11:00. Export queues are healthy.",
    )


async def queues(_context):
    return ListWidgetResult(
        label="Queues",
        items=(
            ListWidgetItem(label="Exports", value="3"),
            ListWidgetItem(label="Imports", value="1"),
            ListWidgetItem(label="Manual reviews", value="12"),
        ),
    )


async def recent_orders(_context):
    return TableWidgetResult(
        label="Recent orders",
        columns=("Order", "Customer", "Status", "Total"),
        rows=tuple(
            (order["id"], order["customer"], order["status"], order["total"])
            for order in _ORDERS
        ),
    )


async def customer_reviews(_context):
    return StatWidgetResult(
        label="Customer reviews",
        value=1,
        description="Account requiring manual review.",
    )


admin.register_widget(
    WidgetDefinition(
        widget_id="pending_orders",
        label="Pending orders",
        loader=pending_orders,
        layout=WidgetLayout(size="small", priority=10),
    )
)
admin.register_widget(
    WidgetDefinition(
        widget_id="operations_note",
        label="Operations note",
        loader=operations_note,
        loading=WidgetLoadingMode.LAZY,
        layout=WidgetLayout(size="medium", priority=20),
    )
)
admin.register_widget(
    WidgetDefinition(
        widget_id="queues",
        label="Queues",
        loader=queues,
        layout=WidgetLayout(size="small", priority=30),
    )
)
admin.register_widget(
    WidgetDefinition(
        widget_id="recent_orders",
        label="Recent orders",
        loader=recent_orders,
        layout=WidgetLayout(size="large", priority=40),
    )
)
admin.register_widget(
    WidgetDefinition(
        widget_id="customer_reviews",
        label="Customer reviews",
        loader=customer_reviews,
        layout=WidgetLayout(size="small", priority=50),
    )
)
admin.register_dashboard(
    DashboardDefinition(
        dashboard_id="main",
        title="Operations dashboard",
        widgets=(
            "pending_orders",
            "operations_note",
            "queues",
            "recent_orders",
            "customer_reviews",
        ),
    )
)
