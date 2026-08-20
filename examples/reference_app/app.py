"""Runnable composition root for Rakit's realistic reference application."""

from __future__ import annotations

import os

from rakit import Admin, SecretValue
from rakit.auth.sqlalchemy import SQLAlchemyAuthPlugin, SQLAlchemyIdempotencyStore
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
from .resources import RESOURCE_ADMINS
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


admin.on_startup(_bootstrap)
admin.add_health_check(
    "database",
    _database_ready,
    critical=True,
    timeout_seconds=2.0,
    cache_seconds=1.0,
)
admin.on_shutdown(dispose_database)

app = admin.asgi()

__all__ = ["ADMIN_ID", "APP_SECRET", "admin", "app"]
