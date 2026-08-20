"""Application-owned SQLAlchemy models for the Rakit reference app."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from rakit.storage import StoredFile
from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy.types import TypeDecorator


def utc_now() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    """Metadata owned by the reference application, never by Rakit auth."""


class StoredFileType(TypeDecorator[dict[str, Any]]):
    """Persist Rakit's portable StoredFile descriptor as application JSON."""

    impl = JSON
    cache_ok = True

    @property
    def python_type(self) -> type[StoredFile]:
        return StoredFile

    def process_bind_param(
        self, value: StoredFile | None, dialect: object
    ) -> dict[str, Any] | None:
        del dialect
        if value is None:
            return None
        if not isinstance(value, StoredFile):
            raise TypeError("product image must be a StoredFile descriptor")
        return value.model_dump(mode="json")

    def process_result_value(self, value: object, dialect: object) -> StoredFile | None:
        del dialect
        if value is None:
            return None
        return StoredFile.model_validate(value)


class Customer(Base):
    __tablename__ = "reference_customers"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    status: Mapped[str] = mapped_column(String(32), default="active", index=True)
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    orders: Mapped[list[Order]] = relationship(back_populates="customer")


class Product(Base):
    __tablename__ = "reference_products"

    id: Mapped[int] = mapped_column(primary_key=True)
    sku: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(200), index=True)
    price_cents: Mapped[int] = mapped_column(Integer)
    inventory_count: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(32), default="active", index=True)
    image: Mapped[StoredFile | None] = mapped_column(StoredFileType(), nullable=True)
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    order_items: Mapped[list[OrderItem]] = relationship(back_populates="product")


class Order(Base):
    __tablename__ = "reference_orders"

    id: Mapped[int] = mapped_column(primary_key=True)
    customer_id: Mapped[int] = mapped_column(
        ForeignKey("reference_customers.id", ondelete="RESTRICT"), index=True
    )
    status: Mapped[str] = mapped_column(String(32), default="pending", index=True)
    total_cents: Mapped[int] = mapped_column(Integer)
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    customer: Mapped[Customer] = relationship(back_populates="orders")
    items: Mapped[list[OrderItem]] = relationship(
        back_populates="order", cascade="all, delete-orphan"
    )


class OrderItem(Base):
    __tablename__ = "reference_order_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    order_id: Mapped[int] = mapped_column(
        ForeignKey("reference_orders.id", ondelete="CASCADE"), index=True
    )
    product_id: Mapped[int] = mapped_column(
        ForeignKey("reference_products.id", ondelete="RESTRICT"), index=True
    )
    quantity: Mapped[int] = mapped_column(Integer)
    unit_price_cents: Mapped[int] = mapped_column(Integer)

    order: Mapped[Order] = relationship(back_populates="items")
    product: Mapped[Product] = relationship(back_populates="order_items")


__all__ = [
    "Base",
    "Customer",
    "Order",
    "OrderItem",
    "Product",
    "StoredFileType",
]
