"""Dashboard widgets and the custom operations page for the reference app."""

from __future__ import annotations

from rakit import (
    DashboardDefinition,
    DomainPageHandler,
    LauncherItem,
    PageDefinition,
    PageResult,
    StatWidgetResult,
    TableWidgetResult,
    WidgetContext,
    WidgetDefinition,
    WidgetLayout,
    WidgetLoadingMode,
    WidgetSize,
)
from rakit.auth.sqlalchemy import User
from sqlalchemy import func, select

from .database import session_factory
from .models import Order, Product


async def _open_orders(_context: WidgetContext) -> StatWidgetResult:
    async with session_factory() as session:
        count = await session.scalar(
            select(func.count(Order.id)).where(Order.status.in_(("pending", "processing")))
        )
    return StatWidgetResult(
        label="Open orders",
        value=int(count or 0),
        description="Pending or processing orders that still need attention.",
    )


async def _low_stock(_context: WidgetContext) -> StatWidgetResult:
    async with session_factory() as session:
        count = await session.scalar(
            select(func.count(Product.id)).where(Product.inventory_count <= 5)
        )
    return StatWidgetResult(
        label="Low stock",
        value=int(count or 0),
        description="Products with five or fewer units available.",
    )


async def _active_users(_context: WidgetContext) -> StatWidgetResult:
    async with session_factory() as session:
        count = await session.scalar(select(func.count(User.id)).where(User.is_active.is_(True)))
    return StatWidgetResult(
        label="Active users",
        value=int(count or 0),
        description="Built-in auth users currently allowed to sign in.",
    )


async def _recent_orders(_context: WidgetContext) -> TableWidgetResult:
    async with session_factory() as session:
        rows = tuple(
            (
                order.id,
                order.customer_id,
                order.status,
                f"${order.total_cents / 100:,.2f}",
            )
            for order in (
                await session.scalars(select(Order).order_by(Order.id.desc()).limit(5))
            ).all()
        )
    return TableWidgetResult(
        label="Recent orders",
        columns=("Order", "Customer", "Status", "Total"),
        rows=rows,
        empty_message="No orders yet.",
    )


async def _operations_page(_context: object) -> PageResult[dict[str, object]]:
    async with session_factory() as session:
        open_orders = await session.scalar(
            select(func.count(Order.id)).where(Order.status.in_(("pending", "processing")))
        )
        low_stock = await session.scalar(
            select(func.count(Product.id)).where(Product.inventory_count <= 5)
        )
        inventory_units = await session.scalar(select(func.sum(Product.inventory_count)))
    return PageResult(
        payload={
            "Open orders": int(open_orders or 0),
            "Low-stock products": int(low_stock or 0),
            "Inventory units": int(inventory_units or 0),
            "Purpose": (
                "This page is application-owned domain logic rendered through Rakit's "
                "public custom-page contract."
            ),
        }
    )


OPEN_ORDERS_WIDGET = WidgetDefinition(
    widget_id="open_orders",
    label="Open orders",
    loader=_open_orders,
    layout=WidgetLayout(size=WidgetSize.SMALL, priority=10),
)

LOW_STOCK_WIDGET = WidgetDefinition(
    widget_id="low_stock",
    label="Low stock",
    loader=_low_stock,
    layout=WidgetLayout(size=WidgetSize.SMALL, priority=20),
)

ACTIVE_USERS_WIDGET = WidgetDefinition(
    widget_id="active_users",
    label="Active users",
    loader=_active_users,
    layout=WidgetLayout(size=WidgetSize.SMALL, priority=30),
)

RECENT_ORDERS_WIDGET = WidgetDefinition(
    widget_id="recent_orders",
    label="Recent orders",
    loader=_recent_orders,
    loading=WidgetLoadingMode.LAZY,
    layout=WidgetLayout(size=WidgetSize.FULL, priority=40),
)

OPERATIONS_PAGE = PageDefinition(
    page_id="operations",
    path="/operations",
    label="Operations summary",
    handler=DomainPageHandler(_operations_page),
)

REFERENCE_DASHBOARD = DashboardDefinition(
    dashboard_id="main",
    title="Reference operations",
    widgets=("open_orders", "low_stock", "active_users", "recent_orders"),
    launchers=(
        LauncherItem(
            launcher_id="orders",
            label="Review orders",
            path="/orders",
            description="Inspect order status and run record or bulk actions.",
        ),
        LauncherItem(
            launcher_id="products",
            label="Manage products",
            path="/products",
            description="Exercise CRUD forms and private image uploads.",
        ),
        LauncherItem(
            launcher_id="operations",
            label="Operations summary",
            path="/operations",
            description="Open the custom application-owned page.",
        ),
    ),
)

REFERENCE_WIDGETS = (
    OPEN_ORDERS_WIDGET,
    LOW_STOCK_WIDGET,
    ACTIVE_USERS_WIDGET,
    RECENT_ORDERS_WIDGET,
)

__all__ = [
    "OPERATIONS_PAGE",
    "REFERENCE_DASHBOARD",
    "REFERENCE_WIDGETS",
]
