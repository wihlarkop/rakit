"""Runnable composition root for Rakit's realistic reference application."""

from __future__ import annotations

import os

from rakit import Admin, SecretValue
from rakit.auth.sqlalchemy import SQLAlchemyAuthPlugin, SQLAlchemyIdempotencyStore
from rakit.core import TokenService
from rakit.sqlalchemy import SQLAlchemyPlugin
from rakit.storage.local import LocalStorage, LocalStoragePlugin
from sqlalchemy import text

from .database import (
    PRODUCT_IMAGE_ROOT,
    bootstrap_database,
    dispose_database,
    engine,
    session_factory,
)
from .resources import ORDER_FORM, PRODUCT_FORM, RESOURCE_ADMINS, order_mutations, product_mutations
from .views import OPERATIONS_PAGE, REFERENCE_DASHBOARD, REFERENCE_WIDGETS

ADMIN_ID = "reference"
APP_SECRET = SecretValue(
    os.environ.get(
        "RAKIT_REFERENCE_SECRET",
        "reference-app-development-secret-change-me-before-production-2026",
    )
)

auth = SQLAlchemyAuthPlugin(session_factory)
idempotency_store = SQLAlchemyIdempotencyStore(session_factory)
token_service = TokenService.single_key(
    key_id="reference",
    value=APP_SECRET,
    admin_id=ADMIN_ID,
)

admin = Admin(
    admin_id=ADMIN_ID,
    title="Rakit Reference Backoffice",
    debug=True,
    secret_key=APP_SECRET,
    auth_backend=auth.auth_backend,
    session_store=auth.session_store,
    operation_idempotency_store=idempotency_store,
)

admin.install(SQLAlchemyPlugin(session_factory=session_factory))
admin.install(
    LocalStoragePlugin(
        storages=(
            LocalStorage(
                storage_id="product-images",
                root=PRODUCT_IMAGE_ROOT,
                allowed_extensions=(".png", ".jpg", ".jpeg", ".webp"),
            ),
        )
    )
)

for resource_admin in RESOURCE_ADMINS:
    admin.register(resource_admin)

admin.register_write(
    "products",
    form_schema=PRODUCT_FORM,
    mutation_service=product_mutations(token_service),
    success_message="Product saved.",
    htmx_refresh_targets=("rakit:dashboard-refresh",),
)
admin.register_write(
    "orders",
    form_schema=ORDER_FORM,
    mutation_service=order_mutations(token_service),
    success_message="Order saved.",
    htmx_refresh_targets=("rakit:dashboard-refresh",),
)

admin.register_page(OPERATIONS_PAGE)
for widget in REFERENCE_WIDGETS:
    admin.register_widget(widget)
admin.register_dashboard(REFERENCE_DASHBOARD)


async def _bootstrap() -> None:
    await bootstrap_database(admin)


async def _database_ready() -> bool:
    try:
        async with engine.connect() as connection:
            await connection.execute(text("SELECT 1"))
        return True
    except Exception:
        return False


admin.lifecycle.register_starting_callback(_bootstrap)
admin.lifecycle.register_health_check(
    "database",
    _database_ready,
    critical=True,
    timeout_seconds=2.0,
    cache_seconds=1.0,
)
admin.lifecycle.register_stopping_callback(dispose_database)

app = admin.asgi()

__all__ = ["ADMIN_ID", "APP_SECRET", "admin", "app"]
