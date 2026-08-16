from rakit import (
    Admin,
    DashboardDefinition,
    ListWidgetItem,
    ListWidgetResult,
    StatWidgetResult,
    TableWidgetResult,
    TextWidgetResult,
    WidgetDefinition,
    WidgetLayout,
    WidgetLoadingMode,
)

admin = Admin(title="Operations", debug=True)


async def pending_orders(_context):
    return StatWidgetResult(
        label="Pending orders",
        value=12,
        description="Orders waiting for review.",
    )


async def operations_note(_context):
    return TextWidgetResult(
        label="Operations note",
        text="Dashboard widgets are isolated read-only operations.",
    )


async def queues(_context):
    return ListWidgetResult(
        label="Queues",
        items=(
            ListWidgetItem(label="Exports", value="3"),
            ListWidgetItem(label="Imports", value="1"),
        ),
    )


async def recent_orders(_context):
    return TableWidgetResult(
        label="Recent orders",
        columns=("Order", "Status"),
        rows=(("#1001", "Pending"), ("#1002", "Approved")),
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
        layout=WidgetLayout(size="medium", priority=30),
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
admin.register_dashboard(
    DashboardDefinition(
        dashboard_id="main",
        title="Operations dashboard",
        widgets=("pending_orders", "operations_note", "queues", "recent_orders"),
    )
)
