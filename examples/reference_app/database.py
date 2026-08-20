"""Async persistence and deterministic development bootstrap for the reference app."""

from __future__ import annotations

import os
from pathlib import Path

from rakit import Admin
from rakit.auth.sqlalchemy import (
    Argon2PasswordHasher,
    AuthBase,
    Permission,
    Role,
    User,
    sync_permissions,
)
from rakit.core import generate_permission_catalogue
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import selectinload

from .models import Base, Customer, Order, OrderItem, Product

REFERENCE_ROOT = Path(os.environ.get("RAKIT_REFERENCE_ROOT", ".rakit-reference"))
DATABASE_PATH = REFERENCE_ROOT / "reference.sqlite3"
UPLOAD_ROOT = REFERENCE_ROOT / "uploads"
PRODUCT_IMAGE_ROOT = UPLOAD_ROOT / "products"

engine = create_async_engine(f"sqlite+aiosqlite:///{DATABASE_PATH.as_posix()}")
session_factory = async_sessionmaker(engine, expire_on_commit=False)

DEMO_PASSWORD = "rakit-demo-password"
ADMIN_EMAIL = "admin@example.com"
OPERATOR_EMAIL = "operator@example.com"
OPERATIONS_ROLE = "operations"


async def _create_tables() -> None:
    REFERENCE_ROOT.mkdir(parents=True, exist_ok=True)
    PRODUCT_IMAGE_ROOT.mkdir(parents=True, exist_ok=True)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
        await connection.run_sync(AuthBase.metadata.create_all)


async def _seed_auth(admin: Admin, session: AsyncSession) -> None:
    compiled = admin.compile()
    catalogue = generate_permission_catalogue(
        admin_id=admin.config.admin_id,
        admin_label=admin.config.title,
        resources=compiled.resources,
        pages=compiled.pages,
        actions=compiled.actions,
        endpoints=compiled.endpoints,
    )
    await sync_permissions(session, catalogue)
    await session.flush()

    hasher = Argon2PasswordHasher()
    password_hash = await hasher.hash(DEMO_PASSWORD)

    admin_user = await session.scalar(select(User).where(User.email == ADMIN_EMAIL))
    if admin_user is None:
        admin_user = User(
            email=ADMIN_EMAIL,
            password_hash=password_hash,
            display_name="Reference Admin",
            is_superuser=True,
        )
        session.add(admin_user)

    operator = await session.scalar(
        select(User).options(selectinload(User.roles)).where(User.email == OPERATOR_EMAIL)
    )
    if operator is None:
        operator = User(
            email=OPERATOR_EMAIL,
            password_hash=password_hash,
            display_name="Reference Operator",
            is_superuser=False,
        )
        session.add(operator)
        await session.flush()

    role = await session.scalar(
        select(Role)
        .options(selectinload(Role.permissions), selectinload(Role.users))
        .where(Role.name == OPERATIONS_ROLE)
    )
    if role is None:
        role = Role(name=OPERATIONS_ROLE)
        session.add(role)
        await session.flush()

    allowed_keys = {
        f"{admin.config.admin_id}.access",
        f"{admin.config.admin_id}.resources.customers.read",
        f"{admin.config.admin_id}.resources.products.read",
        f"{admin.config.admin_id}.resources.products.update",
        f"{admin.config.admin_id}.resources.orders.read",
        f"{admin.config.admin_id}.resources.orders.update",
        f"{admin.config.admin_id}.resources.order_items.read",
        f"{admin.config.admin_id}.pages.operations.view",
        f"{admin.config.admin_id}.actions.mark_paid.execute",
        f"{admin.config.admin_id}.actions.mark_processing.execute",
    }
    permissions = tuple(
        (
            await session.scalars(
                select(Permission).where(
                    Permission.key.in_(allowed_keys), Permission.orphaned.is_(False)
                )
            )
        ).all()
    )
    role.permissions = list(permissions)
    if operator not in role.users:
        role.users.append(operator)


async def _seed_commerce(session: AsyncSession) -> None:
    if await session.scalar(select(Customer.id).limit(1)) is not None:
        return

    ada = Customer(name="Ada Lovelace", email="ada@example.com", status="active")
    grace = Customer(name="Grace Hopper", email="grace@example.com", status="active")
    linus = Customer(name="Linus Torvalds", email="linus@example.com", status="review")
    session.add_all((ada, grace, linus))

    keyboard = Product(
        sku="RKT-KB-001",
        name="Rakit Mechanical Keyboard",
        price_cents=14900,
        inventory_count=18,
        status="active",
    )
    headphones = Product(
        sku="RKT-HP-002",
        name="Studio Headphones",
        price_cents=22900,
        inventory_count=4,
        status="active",
    )
    dock = Product(
        sku="RKT-DK-003",
        name="USB-C Desk Dock",
        price_cents=9900,
        inventory_count=0,
        status="backorder",
    )
    session.add_all((keyboard, headphones, dock))
    await session.flush()

    first_order = Order(customer=ada, status="pending", total_cents=37800)
    first_order.items.extend(
        (
            OrderItem(product=keyboard, quantity=1, unit_price_cents=14900),
            OrderItem(product=headphones, quantity=1, unit_price_cents=22900),
        )
    )
    second_order = Order(customer=grace, status="processing", total_cents=19800)
    second_order.items.append(OrderItem(product=dock, quantity=2, unit_price_cents=9900))
    session.add_all((first_order, second_order))


async def bootstrap_database(admin: Admin) -> None:
    """Create and seed the development database without destructive resets."""

    await _create_tables()
    async with session_factory() as session:
        async with session.begin():
            await _seed_auth(admin, session)
            await _seed_commerce(session)


async def dispose_database() -> None:
    await engine.dispose()


__all__ = [
    "ADMIN_EMAIL",
    "DATABASE_PATH",
    "DEMO_PASSWORD",
    "OPERATIONS_ROLE",
    "OPERATOR_EMAIL",
    "PRODUCT_IMAGE_ROOT",
    "REFERENCE_ROOT",
    "bootstrap_database",
    "dispose_database",
    "engine",
    "session_factory",
]
