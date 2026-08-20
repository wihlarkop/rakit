"""Public Rakit resource declarations for the reference backoffice."""

from __future__ import annotations

from rakit import (
    ActionContext,
    ActionDefinition,
    ActionScope,
    ActionSuccess,
    ApiExposure,
    BulkExecutionPolicy,
    BulkPolicy,
    ChoiceFilter,
    DomainActionExecutor,
    FieldDefinition,
    FileField,
    FilterChoice,
    ModelAdmin,
    RelationshipCardinality,
    RelationshipDefinition,
    RelationshipEditMode,
    RelationshipKind,
    ResourceApiDefinition,
    TransactionPolicy,
)
from rakit.core import FormSchema, TokenService
from rakit.sqlalchemy import SQLAlchemyMutationService
from sqlalchemy import update

from .database import session_factory
from .models import Customer, Order, OrderItem, Product


def _identity_id(context: ActionContext) -> int:
    if context.identity is None:
        raise ValueError("record action requires an identity")
    value = context.identity.values.get("id")
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValueError("reference resources use integer identities")
    return value


async def _mark_paid(context: ActionContext) -> ActionSuccess[None]:
    order_id = _identity_id(context)
    async with session_factory() as session:
        async with session.begin():
            await session.execute(
                update(Order)
                .where(Order.id == order_id)
                .values(status="paid", version=Order.version + 1)
            )
    return ActionSuccess(message=f"Order #{order_id} marked paid.")


async def _mark_processing(context: ActionContext) -> ActionSuccess[None]:
    order_id = _identity_id(context)
    async with session_factory() as session:
        async with session.begin():
            await session.execute(
                update(Order)
                .where(Order.id == order_id)
                .values(status="processing", version=Order.version + 1)
            )
    return ActionSuccess(message=f"Order #{order_id} moved to processing.")


MARK_PAID = ActionDefinition(
    action_id="mark_paid",
    label="Mark paid",
    description="Move one order to the paid state using an application-owned transaction.",
    scope=ActionScope.RECORD,
    resource_id="orders",
    executor=DomainActionExecutor(_mark_paid),
    mutating=True,
    transaction_policy=TransactionPolicy.DISABLED,
)

MARK_PROCESSING = ActionDefinition(
    action_id="mark_processing",
    label="Move to processing",
    description="Best-effort bulk transition for selected orders.",
    scope=ActionScope.BULK,
    resource_id="orders",
    executor=DomainActionExecutor(_mark_processing),
    mutating=True,
    transaction_policy=TransactionPolicy.DISABLED,
    bulk_policy=BulkPolicy(
        execution=BulkExecutionPolicy.BEST_EFFORT,
        confirmation_threshold=2,
        synchronous_maximum=100,
        require_concurrency_snapshot=False,
    ),
)

CUSTOMER_STATUS = ChoiceFilter(
    filter_id="customer_status",
    label="Status",
    field="status",
    choices=(
        FilterChoice(value="active", label="Active"),
        FilterChoice(value="review", label="Needs review"),
    ),
)

PRODUCT_STATUS = ChoiceFilter(
    filter_id="product_status",
    label="Status",
    field="status",
    choices=(
        FilterChoice(value="active", label="Active"),
        FilterChoice(value="backorder", label="Backorder"),
        FilterChoice(value="archived", label="Archived"),
    ),
)

ORDER_STATUS = ChoiceFilter(
    filter_id="order_status",
    label="Status",
    field="status",
    choices=(
        FilterChoice(value="pending", label="Pending"),
        FilterChoice(value="processing", label="Processing"),
        FilterChoice(value="paid", label="Paid"),
        FilterChoice(value="cancelled", label="Cancelled"),
    ),
)

ORDER_CUSTOMER = RelationshipDefinition(
    relationship_id="customer",
    target_resource_id="customers",
    label="Customer",
    kind=RelationshipKind.MANY_TO_ONE,
    cardinality=RelationshipCardinality.TO_ONE,
    nullable=False,
    writable=False,
    edit_mode=RelationshipEditMode.READ_ONLY,
    record_label_field="name",
)


class CustomerAdmin(ModelAdmin):
    resource_id = "customers"
    path = "/customers"
    label = "Customers"
    singular_label = "Customer"
    model = Customer
    list_fields = ("id", "name", "email", "status", "created_at")
    detail_fields = ("id", "name", "email", "status", "created_at")
    filters = (CUSTOMER_STATUS,)
    search_fields = ("name", "email")
    sort_fields = ("id", "name", "created_at")
    api = ResourceApiDefinition(
        exposure=ApiExposure.READ_ONLY,
        read_fields=("id", "name", "email", "status", "created_at"),
        filters=("customer_status",),
    )


class ProductAdmin(ModelAdmin):
    resource_id = "products"
    path = "/products"
    label = "Products"
    singular_label = "Product"
    model = Product
    list_fields = ("id", "sku", "name", "price_cents", "inventory_count", "status")
    detail_fields = (
        "id",
        "sku",
        "name",
        "price_cents",
        "inventory_count",
        "status",
        "image",
        "created_at",
    )
    filters = (PRODUCT_STATUS,)
    search_fields = ("sku", "name")
    sort_fields = ("id", "sku", "name", "price_cents", "inventory_count", "created_at")
    api = ResourceApiDefinition(
        exposure=ApiExposure.READ_ONLY,
        read_fields=("id", "sku", "name", "price_cents", "inventory_count", "status"),
        filters=("product_status",),
    )


class OrderAdmin(ModelAdmin):
    resource_id = "orders"
    path = "/orders"
    label = "Orders"
    singular_label = "Order"
    model = Order
    list_fields = ("id", "customer_id", "status", "total_cents", "created_at")
    detail_fields = ("id", "customer_id", "status", "total_cents", "created_at")
    filters = (ORDER_STATUS,)
    sort_fields = ("id", "total_cents", "created_at")
    relationships = (ORDER_CUSTOMER,)
    actions = (MARK_PAID, MARK_PROCESSING)
    api = ResourceApiDefinition(
        exposure=ApiExposure.READ_ONLY,
        read_fields=("id", "customer_id", "status", "total_cents", "created_at"),
        filters=("order_status",),
    )


class OrderItemAdmin(ModelAdmin):
    resource_id = "order_items"
    path = "/order-items"
    label = "Order items"
    singular_label = "Order item"
    model = OrderItem
    list_fields = ("id", "order_id", "product_id", "quantity", "unit_price_cents")
    detail_fields = ("id", "order_id", "product_id", "quantity", "unit_price_cents")
    sort_fields = ("id", "order_id", "product_id")


PRODUCT_FORM = FormSchema(
    fields=(
        FieldDefinition(field_id="sku", python_type=str, label="SKU", required=True),
        FieldDefinition(field_id="name", python_type=str, label="Name", required=True),
        FieldDefinition(
            field_id="price_cents",
            python_type=int,
            label="Price (cents)",
            required=True,
            description="Stored as integer cents to keep the example deterministic.",
        ),
        FieldDefinition(
            field_id="inventory_count",
            python_type=int,
            label="Inventory",
            required=True,
        ),
        FieldDefinition(field_id="status", python_type=str, label="Status", required=True),
        FileField(
            field_id="image",
            label="Product image",
            nullable=True,
            allow_empty=True,
            storage_id="product-images",
            prefix="catalog",
            max_size=2 * 1024 * 1024,
            allowed_extensions=(".png", ".jpg", ".jpeg", ".webp"),
            allowed_mime_types=("image/png", "image/jpeg", "image/webp"),
            delete_behavior="delete",
            description="Optional private image, stored through Rakit's local storage adapter.",
        ),
    )
)

ORDER_FORM = FormSchema(
    fields=(
        FieldDefinition(
            field_id="customer_id", python_type=int, label="Customer ID", required=True
        ),
        FieldDefinition(field_id="status", python_type=str, label="Status", required=True),
        FieldDefinition(
            field_id="total_cents", python_type=int, label="Total (cents)", required=True
        ),
    )
)


def product_mutations(token_service: TokenService) -> SQLAlchemyMutationService:
    return SQLAlchemyMutationService(
        model=Product,
        session_factory=session_factory,
        form_schema=PRODUCT_FORM,
        writable_fields=("sku", "name", "price_cents", "inventory_count", "status", "image"),
        identity_fields=("id",),
        token_service=token_service,
        version_field="version",
        resource_id="products",
        delete_permission="reference.resources.products.delete",
        force_overwrite_permission="reference.resources.products.force_overwrite",
    )


def order_mutations(token_service: TokenService) -> SQLAlchemyMutationService:
    return SQLAlchemyMutationService(
        model=Order,
        session_factory=session_factory,
        form_schema=ORDER_FORM,
        writable_fields=("customer_id", "status", "total_cents"),
        identity_fields=("id",),
        token_service=token_service,
        version_field="version",
        resource_id="orders",
        delete_permission="reference.resources.orders.delete",
        force_overwrite_permission="reference.resources.orders.force_overwrite",
    )


RESOURCE_ADMINS = (CustomerAdmin, ProductAdmin, OrderAdmin, OrderItemAdmin)

__all__ = [
    "CUSTOMER_STATUS",
    "MARK_PAID",
    "MARK_PROCESSING",
    "ORDER_FORM",
    "ORDER_STATUS",
    "PRODUCT_FORM",
    "PRODUCT_STATUS",
    "RESOURCE_ADMINS",
    "CustomerAdmin",
    "OrderAdmin",
    "OrderItemAdmin",
    "ProductAdmin",
    "order_mutations",
    "product_mutations",
]
