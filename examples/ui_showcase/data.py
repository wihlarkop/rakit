"""Deterministic commerce/operations records used by the UI showcase."""

from __future__ import annotations

CUSTOMERS: tuple[dict[str, object], ...] = (
    {
        "id": "CUS-001",
        "name": "Atlas Research & Engineering Cooperative — International Operations",
        "segment": "Enterprise",
        "status": "Active",
        "owner": "Maya Chen",
        "email": "ops@atlas.example",
    },
    {
        "id": "CUS-002",
        "name": "Northstar Labs",
        "segment": "Scale",
        "status": "Active",
        "owner": "Owen Park",
        "email": "hello@northstar.example",
    },
    {
        "id": "CUS-003",
        "name": "Acme Studio",
        "segment": "Team",
        "status": "Review",
        "owner": "Maya Chen",
        "email": None,
    },
    {
        "id": "CUS-004",
        "name": "Vertex Supply",
        "segment": "Scale",
        "status": "Active",
        "owner": "Rina Patel",
        "email": "orders@vertex.example",
    },
    {
        "id": "CUS-005",
        "name": "Juniper Works",
        "segment": "Team",
        "status": "Paused",
        "owner": "Owen Park",
        "email": "team@juniper.example",
    },
    {
        "id": "CUS-006",
        "name": "Harbor Systems",
        "segment": "Enterprise",
        "status": "Active",
        "owner": "Rina Patel",
        "email": "purchasing@harbor.example",
    },
)

CATEGORIES: tuple[dict[str, object], ...] = (
    {"id": "CAT-01", "name": "Workspace", "status": "Active", "products": 3},
    {"id": "CAT-02", "name": "Input devices", "status": "Active", "products": 2},
    {"id": "CAT-03", "name": "Displays", "status": "Active", "products": 2},
    {"id": "CAT-04", "name": "Accessories", "status": "Review", "products": 1},
)

PRODUCTS: tuple[dict[str, object], ...] = (
    {
        "id": "PRD-101",
        "name": "Precision mechanical keyboard with low-profile tactile switches",
        "category": "Input devices",
        "sku": "KEY-LP-01",
        "status": "Published",
        "price": "$149.00",
    },
    {
        "id": "PRD-102",
        "name": "Studio wireless mouse",
        "category": "Input devices",
        "sku": "MSE-WL-02",
        "status": "Published",
        "price": "$89.00",
    },
    {
        "id": "PRD-103",
        "name": "27-inch color-accurate display",
        "category": "Displays",
        "sku": "DSP-27-4K",
        "status": "Published",
        "price": "$529.00",
    },
    {
        "id": "PRD-104",
        "name": "Portable 16-inch display",
        "category": "Displays",
        "sku": "DSP-16-P",
        "status": "Draft",
        "price": "$319.00",
    },
    {
        "id": "PRD-105",
        "name": "Adjustable monitor arm",
        "category": "Workspace",
        "sku": "ARM-DUAL-01",
        "status": "Published",
        "price": "$179.00",
    },
    {
        "id": "PRD-106",
        "name": "Compact standing desk",
        "category": "Workspace",
        "sku": "DSK-ST-02",
        "status": "Published",
        "price": "$689.00",
    },
    {
        "id": "PRD-107",
        "name": "Cable management tray",
        "category": "Workspace",
        "sku": "CBL-TRAY-01",
        "status": "Archived",
        "price": "$39.00",
    },
    {
        "id": "PRD-108",
        "name": "USB-C travel hub",
        "category": "Accessories",
        "sku": "HUB-USBC-08",
        "status": "Review",
        "price": "$79.00",
    },
)

INVENTORY: tuple[dict[str, object], ...] = (
    {
        "id": "INV-101",
        "sku": "KEY-LP-01",
        "product": "Precision mechanical keyboard",
        "on_hand": 48,
        "reorder_at": 20,
        "status": "Healthy",
    },
    {
        "id": "INV-102",
        "sku": "MSE-WL-02",
        "product": "Studio wireless mouse",
        "on_hand": 7,
        "reorder_at": 16,
        "status": "Low stock",
    },
    {
        "id": "INV-103",
        "sku": "DSP-27-4K",
        "product": "27-inch color-accurate display",
        "on_hand": 3,
        "reorder_at": 8,
        "status": "Low stock",
    },
    {
        "id": "INV-104",
        "sku": "DSP-16-P",
        "product": "Portable 16-inch display",
        "on_hand": 22,
        "reorder_at": 10,
        "status": "Healthy",
    },
    {
        "id": "INV-105",
        "sku": "ARM-DUAL-01",
        "product": "Adjustable monitor arm",
        "on_hand": 0,
        "reorder_at": 12,
        "status": "Out of stock",
    },
    {
        "id": "INV-106",
        "sku": "DSK-ST-02",
        "product": "Compact standing desk",
        "on_hand": 15,
        "reorder_at": 6,
        "status": "Healthy",
    },
)

TEAMS: tuple[dict[str, object], ...] = (
    {
        "id": "TEAM-OPS",
        "name": "Commerce operations",
        "lead": "Maya Chen",
        "members": 8,
        "status": "On duty",
    },
    {
        "id": "TEAM-FUL",
        "name": "Fulfilment",
        "lead": "Owen Park",
        "members": 12,
        "status": "On duty",
    },
    {
        "id": "TEAM-CAT",
        "name": "Catalog quality",
        "lead": "Rina Patel",
        "members": 5,
        "status": "On duty",
    },
)

_CUSTOMER_ORDER_NAMES = tuple(str(customer["name"]) for customer in CUSTOMERS)
_ORDER_STATUSES = ("Paid", "Pending review", "Processing", "Fulfilled", "Refunded", "Cancelled")


def _order(index: int) -> dict[str, object]:
    customer = _CUSTOMER_ORDER_NAMES[index % len(_CUSTOMER_ORDER_NAMES)]
    status = _ORDER_STATUSES[index % len(_ORDER_STATUSES)]
    day = 17 - (index % 10)
    total = 84 + ((index * 137) % 2200)
    return {
        "id": f"ORD-{1080 - index:04d}",
        "customer": customer,
        "status": status,
        "items": 1 + (index % 5),
        "total": f"${total:,.2f}",
        "created": f"2026-08-{day:02d}",
    }


ORDERS: tuple[dict[str, object], ...] = tuple(_order(index) for index in range(32))
