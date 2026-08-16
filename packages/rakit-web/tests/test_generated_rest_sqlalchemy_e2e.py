import asyncio
import sqlite3
from datetime import UTC, datetime, timedelta

from rakit import Admin, ApiExposure, ModelAdmin, ResourceApiDefinition, SecretValue
from rakit_core.auth import Principal, SessionRecord
from rakit_core.concurrency import AttributeVersionProvider
from rakit_core.crypto import TokenService
from rakit_core.idempotency import IdempotencyReservation, IdempotencyStatus, OperationReceipt
from rakit_sqlalchemy.plugin import SQLAlchemyPlugin
from rakit_web.security.cookies import CSRF_COOKIE_NAME, SESSION_COOKIE_NAME
from rakit_web.security.csrf import CsrfService
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from starlette.testclient import TestClient


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "generated_e2e_users"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str]
    version: Mapped[int] = mapped_column(default=1)


class UsersAdmin(ModelAdmin):
    model = User
    resource_id = "users"
    path = "/users"
    label = "Users"
    singular_label = "User"
    list_fields = ("id", "email", "version")
    detail_fields = ("id", "email", "version")
    api = ResourceApiDefinition(
        exposure=ApiExposure.CRUD,
        read_fields=("id", "email", "version"),
        create_fields=("email",),
        update_fields=("email",),
    )


SESSION = SessionRecord(
    session_id="session-1",
    subject_id="user-1",
    created_at=datetime.now(UTC),
    last_seen_at=datetime.now(UTC),
    idle_expires_at=datetime.now(UTC) + timedelta(hours=1),
    absolute_expires_at=datetime.now(UTC) + timedelta(days=1),
)


class AuthBackend:
    async def authenticate(self, identifier: str, password: str):
        return None

    async def resolve_principal(self, subject_id: str):
        if subject_id != "user-1":
            return None
        return Principal(
            subject_id="user-1",
            authenticated=True,
            permissions=frozenset(
                {
                    "admin.resources.users.read",
                    "admin.resources.users.create",
                    "admin.resources.users.update",
                    "admin.resources.users.delete",
                }
            ),
        )


class SessionStore:
    production_safe = False

    async def create(self, principal: Principal):
        raise NotImplementedError

    async def resolve(self, raw_token: str):
        return SESSION if raw_token == "valid" else None

    async def rotate(self, session_id: str):
        raise NotImplementedError

    async def revoke(self, session_id: str):
        return None


class MemoryIdempotencyStore:
    production_safe = False

    def __init__(self) -> None:
        self._next = 1
        self._entries: dict[str, tuple[str, IdempotencyReservation]] = {}

    async def begin(self, token_hash: str, *, fingerprint: str) -> IdempotencyReservation:
        existing = self._entries.get(token_hash)
        if existing is not None:
            existing_fingerprint, reservation = existing
            if existing_fingerprint != fingerprint:
                raise ValueError("fingerprint mismatch")
            if reservation.status is IdempotencyStatus.COMPLETED:
                return reservation
            return IdempotencyReservation(
                reservation_id=reservation.reservation_id,
                status=reservation.status,
                completed_receipt=reservation.completed_receipt,
                claimed=False,
                claim_generation=reservation.claim_generation,
            )
        reservation = IdempotencyReservation(
            reservation_id=self._next,
            status=IdempotencyStatus.IN_PROGRESS,
        )
        self._next += 1
        self._entries[token_hash] = (fingerprint, reservation)
        return reservation

    async def complete(self, reservation, receipt: OperationReceipt) -> None:
        for key, (fingerprint, existing) in tuple(self._entries.items()):
            if existing.reservation_id == reservation.reservation_id:
                self._entries[key] = (
                    fingerprint,
                    IdempotencyReservation(
                        reservation_id=reservation.reservation_id,
                        status=IdempotencyStatus.COMPLETED,
                        completed_receipt=receipt,
                    ),
                )
                return
        raise AssertionError("reservation missing")

    async def release(self, reservation) -> None:
        for key, (_, existing) in tuple(self._entries.items()):
            if existing.reservation_id == reservation.reservation_id:
                del self._entries[key]

    async def fail_final(self, reservation) -> None:
        return None


def test_generated_crud_runs_end_to_end_through_admin_and_sqlalchemy(tmp_path) -> None:
    database_path = tmp_path / "generated-rest.sqlite3"
    with sqlite3.connect(database_path) as connection:
        connection.execute(
            "CREATE TABLE generated_e2e_users ("
            "id INTEGER PRIMARY KEY AUTOINCREMENT, "
            "email TEXT NOT NULL, "
            "version INTEGER NOT NULL DEFAULT 1"
            ")"
        )

    engine = create_async_engine(f"sqlite+aiosqlite:///{database_path}")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    secret = SecretValue("x" * 32)
    admin = Admin(
        title="Generated CRUD E2E",
        debug=True,
        secret_key=secret,
        auth_backend=AuthBackend(),
        session_store=SessionStore(),
        operation_idempotency_store=MemoryIdempotencyStore(),
    )
    admin.install(SQLAlchemyPlugin(session_factory=session_factory))
    admin.register(UsersAdmin)
    admin.register_concurrency_provider("users", AttributeVersionProvider("version"))
    app = admin.asgi()

    csrf_token = CsrfService(
        TokenService.single_key(
            key_id="primary",
            value=secret,
            admin_id="admin",
        )
    ).issue(SESSION)
    headers = {"X-CSRF-Token": csrf_token}

    with TestClient(app, base_url="http://localhost") as client:
        client.cookies.set(SESSION_COOKIE_NAME, "valid")
        client.cookies.set(CSRF_COOKIE_NAME, csrf_token)

        created = client.post(
            "/api/users",
            json={"email": "first@example.com"},
            headers={**headers, "Idempotency-Key": "create-1"},
        )
        assert created.status_code == 201
        assert created.json()["data"] == {
            "id": 1,
            "email": "first@example.com",
            "version": 1,
        }
        location = created.headers["location"]

        detail = client.get(location)
        assert detail.status_code == 200
        original_etag = detail.headers["etag"]

        updated = client.patch(
            location,
            json={"email": "next@example.com"},
            headers={
                **headers,
                "Idempotency-Key": "update-1",
                "If-Match": original_etag,
            },
        )
        assert updated.status_code == 200
        assert updated.json()["data"] == {
            "id": 1,
            "email": "next@example.com",
            "version": 2,
        }
        current_etag = updated.headers["etag"]
        assert current_etag != original_etag

        stale = client.patch(
            location,
            json={"email": "stale@example.com"},
            headers={
                **headers,
                "Idempotency-Key": "update-stale",
                "If-Match": original_etag,
            },
        )
        assert stale.status_code == 409
        assert stale.json()["error"]["code"] == "resource.conflict"

        deleted = client.delete(
            location,
            headers={
                **headers,
                "Idempotency-Key": "delete-1",
                "If-Match": current_etag,
            },
        )
        assert deleted.status_code == 204

    with sqlite3.connect(database_path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM generated_e2e_users").fetchone()[0] == 0

    asyncio.run(engine.dispose())
