from datetime import UTC, datetime, timedelta

import pytest
from rakit import Admin, ApiExposure, ModelAdmin, ResourceApiDefinition, SecretValue
from rakit_core.auth import Principal, SessionRecord
from rakit_core.idempotency import IdempotencyReservation, IdempotencyStatus, OperationReceipt
from rakit_sqlalchemy.plugin import SQLAlchemyPlugin
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "generated_admin_users"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str]


class UsersAdmin(ModelAdmin):
    model = User
    resource_id = "users"
    path = "/users"
    label = "Users"
    singular_label = "User"
    list_fields = ("id", "email")
    detail_fields = ("id", "email")
    api = ResourceApiDefinition(
        exposure=ApiExposure.CRUD,
        read_fields=("id", "email"),
        create_fields=("email",),
        update_fields=("email",),
    )


class AuthBackend:
    async def authenticate(self, identifier: str, password: str):
        return None

    async def resolve_principal(self, subject_id: str):
        return Principal(subject_id=subject_id, authenticated=True, permissions=frozenset())


class SessionStore:
    production_safe = False

    async def create(self, principal: Principal):
        raise NotImplementedError

    async def resolve(self, raw_token: str):
        now = datetime.now(UTC)
        return SessionRecord(
            session_id="session-1",
            subject_id="user-1",
            created_at=now,
            last_seen_at=now,
            idle_expires_at=now + timedelta(hours=1),
            absolute_expires_at=now + timedelta(days=1),
        )

    async def rotate(self, session_id: str):
        raise NotImplementedError

    async def revoke(self, session_id: str):
        return None


class IdempotencyStore:
    production_safe = False

    async def begin(self, token_hash: str, *, fingerprint: str):
        return IdempotencyReservation(1, IdempotencyStatus.IN_PROGRESS)

    async def complete(self, reservation, receipt: OperationReceipt):
        return None

    async def release(self, reservation):
        return None

    async def fail_final(self, reservation):
        return None


def _admin(*, auth: bool, idempotency: bool) -> Admin:
    kwargs = {}
    if auth:
        kwargs.update(
            auth_backend=AuthBackend(),
            session_store=SessionStore(),
            secret_key=SecretValue("x" * 32),
        )
    if idempotency:
        kwargs["operation_idempotency_store"] = IdempotencyStore()
    admin = Admin(title="Generated CRUD", debug=True, **kwargs)
    admin.install(SQLAlchemyPlugin(session_factory=async_sessionmaker[AsyncSession]()))
    admin.register(UsersAdmin)
    return admin


def test_generated_crud_runtime_requires_authentication() -> None:
    admin = _admin(auth=False, idempotency=True)

    with pytest.raises(Exception) as captured:
        admin.asgi()

    error = captured.value
    assert getattr(error, "details")["reason"] == "generated_api_auth_required"


def test_generated_crud_runtime_requires_idempotency_store() -> None:
    admin = _admin(auth=True, idempotency=False)

    with pytest.raises(Exception) as captured:
        admin.asgi()

    error = captured.value
    assert getattr(error, "details")["reason"] == "generated_api_idempotency_store_required"


def test_generated_crud_runtime_materializes_when_dependencies_are_complete() -> None:
    admin = _admin(auth=True, idempotency=True)

    app = admin.asgi()

    assert app is not None
