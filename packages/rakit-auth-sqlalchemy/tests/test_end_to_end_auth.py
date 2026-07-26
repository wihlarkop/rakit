"""End-to-end: createsuperuser -> built-in login -> authenticated request.

Uses the *real* SQLAlchemyAuthBackend and SQLAlchemySessionStore against a
real database -- not the in-memory doubles rakit-web's own suite uses --
so this proves the concrete built-in path actually works together, which
was the specific gap the external review identified ("createsuperuser
creates a user that cannot use a built-in login backend").
"""

import asyncio
from collections.abc import AsyncIterator

import httpx
import pytest
from rakit import Admin, ModelAdmin, SecretValue
from rakit_auth_sqlalchemy.models import Base as AuthBase
from rakit_auth_sqlalchemy.models import Permission, Role, User
from rakit_auth_sqlalchemy.passwords import Argon2PasswordHasher
from rakit_auth_sqlalchemy.plugin import SQLAlchemyAuthPlugin
from rakit_sqlalchemy.plugin import SQLAlchemyPlugin
from rakit_web.security.rate_limit import LoginRateLimiter
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, selectinload
from starlette.types import ASGIApp


class _TestRateLimiter(LoginRateLimiter):
    production_safe = True


class _LifespanDriver:
    def __init__(self, app: ASGIApp) -> None:
        self._app = app
        self._receive_queue: asyncio.Queue = asyncio.Queue()
        self._startup_complete = asyncio.Event()
        self._shutdown_complete = asyncio.Event()
        self._task: asyncio.Task | None = None

    async def __aenter__(self) -> "_LifespanDriver":
        async def receive():
            return await self._receive_queue.get()

        async def send(message):
            if message["type"].startswith("lifespan.startup"):
                self._startup_complete.set()
            elif message["type"].startswith("lifespan.shutdown"):
                self._shutdown_complete.set()

        async def run_app() -> None:
            await self._app({"type": "lifespan"}, receive, send)

        self._task = asyncio.create_task(run_app())
        await self._receive_queue.put({"type": "lifespan.startup"})
        await self._startup_complete.wait()
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        await self._receive_queue.put({"type": "lifespan.shutdown"})
        await self._shutdown_complete.wait()
        assert self._task is not None
        await self._task


class AppBase(DeclarativeBase):
    pass


class Widget(AppBase):
    __tablename__ = "widgets"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str]


class WidgetAdmin(ModelAdmin):
    resource_id = "widgets"
    path = "/widgets"
    label = "Widgets"
    singular_label = "Widget"
    model = Widget
    list_fields = ("id", "name")
    detail_fields = ("id", "name")


@pytest.fixture
async def session_factory() -> AsyncIterator[async_sessionmaker]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(AuthBase.metadata.create_all)
        await conn.run_sync(AppBase.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        session.add(Widget(id=1, name="Sprocket"))
        await session.commit()
    yield factory
    await engine.dispose()


async def _create_superuser(session_factory, *, email: str, password: str) -> None:
    """Exactly what `rakit createsuperuser` does: Argon2-hash the password
    and insert a User with is_superuser=True."""
    hasher = Argon2PasswordHasher()
    password_hash = await hasher.hash(password)
    async with session_factory() as session:
        session.add(User(email=email, password_hash=password_hash, is_superuser=True))
        await session.commit()


async def _create_user_with_permissions(
    session_factory, *, email: str, password: str, permission_keys: tuple[str, ...]
) -> None:
    hasher = Argon2PasswordHasher()
    password_hash = await hasher.hash(password)
    async with session_factory() as session:
        role = Role(name="operator")
        for key in permission_keys:
            role.permissions.append(Permission(key=key))
        user = User(email=email, password_hash=password_hash)
        user.roles.append(role)
        session.add(user)
        await session.commit()


def _build_admin(session_factory) -> Admin:
    auth = SQLAlchemyAuthPlugin(session_factory)
    admin = Admin(
        admin_id="operations",
        title="Operations",
        debug=False,
        secret_key=SecretValue("x" * 32),
        auth_backend=auth.auth_backend,
        session_store=auth.session_store,
        login_rate_limiter=_TestRateLimiter(),
    )
    admin.install(SQLAlchemyPlugin(session_factory=session_factory))
    admin.register(WidgetAdmin)
    return admin


async def test_createsuperuser_then_login_then_authenticated_request(session_factory) -> None:
    await _create_superuser(session_factory, email="admin@example.com", password="secret-password")
    app = _build_admin(session_factory).asgi()
    transport = httpx.ASGITransport(app=app)

    async with (
        _LifespanDriver(app),
        httpx.AsyncClient(transport=transport, base_url="http://localhost") as client,
    ):
        # Anonymous: not served.
        anonymous = await client.get("/widgets", follow_redirects=False)
        assert anonymous.status_code == 303
        assert "Sprocket" not in anonymous.text

        # Log in with the credentials createsuperuser would have created.
        login = await client.post(
            "/auth/login",
            data={"identifier": "admin@example.com", "password": "secret-password"},
            follow_redirects=False,
        )
        assert login.status_code == 303
        client.cookies.set("rakit_session", login.cookies["rakit_session"])

        # Authenticated superuser: served.
        authorized = await client.get("/widgets")
        assert authorized.status_code == 200
        assert "Sprocket" in authorized.text


async def test_login_is_case_insensitive_for_the_stored_email(session_factory) -> None:
    await _create_superuser(session_factory, email="Admin@Example.COM", password="secret-password")
    app = _build_admin(session_factory).asgi()
    transport = httpx.ASGITransport(app=app)

    async with (
        _LifespanDriver(app),
        httpx.AsyncClient(transport=transport, base_url="http://localhost") as client,
    ):
        login = await client.post(
            "/auth/login",
            data={"identifier": "admin@example.com", "password": "secret-password"},
            follow_redirects=False,
        )
        assert login.status_code == 303


async def test_role_permission_grants_resource_access(session_factory) -> None:
    await _create_user_with_permissions(
        session_factory,
        email="operator@example.com",
        password="secret-password",
        permission_keys=("operations.access", "operations.resources.widgets.read"),
    )
    app = _build_admin(session_factory).asgi()
    transport = httpx.ASGITransport(app=app)

    async with (
        _LifespanDriver(app),
        httpx.AsyncClient(transport=transport, base_url="http://localhost") as client,
    ):
        login = await client.post(
            "/auth/login",
            data={"identifier": "operator@example.com", "password": "secret-password"},
            follow_redirects=False,
        )
        assert login.status_code == 303
        client.cookies.set("rakit_session", login.cookies["rakit_session"])

        response = await client.get("/widgets")
        assert response.status_code == 200
        assert "Sprocket" in response.text


async def test_missing_resource_permission_returns_403(session_factory) -> None:
    await _create_user_with_permissions(
        session_factory,
        email="operator@example.com",
        password="secret-password",
        permission_keys=("operations.access",),  # access, but not widgets.read
    )
    app = _build_admin(session_factory).asgi()
    transport = httpx.ASGITransport(app=app)

    async with (
        _LifespanDriver(app),
        httpx.AsyncClient(transport=transport, base_url="http://localhost") as client,
    ):
        login = await client.post(
            "/auth/login",
            data={"identifier": "operator@example.com", "password": "secret-password"},
            follow_redirects=False,
        )
        client.cookies.set("rakit_session", login.cookies["rakit_session"])

        response = await client.get("/widgets", follow_redirects=False)
        assert response.status_code == 403
        assert "Sprocket" not in response.text


async def test_inactive_user_cannot_authenticate(session_factory) -> None:
    hasher = Argon2PasswordHasher()
    password_hash = await hasher.hash("secret-password")
    async with session_factory() as session:
        session.add(User(email="dormant@example.com", password_hash=password_hash, is_active=False))
        await session.commit()

    app = _build_admin(session_factory).asgi()
    transport = httpx.ASGITransport(app=app)

    async with (
        _LifespanDriver(app),
        httpx.AsyncClient(transport=transport, base_url="http://localhost") as client,
    ):
        login = await client.post(
            "/auth/login",
            data={"identifier": "dormant@example.com", "password": "secret-password"},
            follow_redirects=False,
        )
        assert login.status_code == 401
        assert "rakit_session" not in login.cookies


async def test_deactivating_a_user_mid_session_revokes_access(session_factory) -> None:
    """A user deactivated after logging in must lose access on the very
    next request -- proving the principal is re-resolved per request, not
    frozen at login."""
    await _create_user_with_permissions(
        session_factory,
        email="operator@example.com",
        password="secret-password",
        permission_keys=("operations.access", "operations.resources.widgets.read"),
    )
    app = _build_admin(session_factory).asgi()
    transport = httpx.ASGITransport(app=app)

    async with (
        _LifespanDriver(app),
        httpx.AsyncClient(transport=transport, base_url="http://localhost") as client,
    ):
        login = await client.post(
            "/auth/login",
            data={"identifier": "operator@example.com", "password": "secret-password"},
            follow_redirects=False,
        )
        client.cookies.set("rakit_session", login.cookies["rakit_session"])
        assert (await client.get("/widgets")).status_code == 200

        async with session_factory() as session:
            user = (
                await session.execute(select(User).where(User.email == "operator@example.com"))
            ).scalar_one()
            user.is_active = False
            await session.commit()

        after = await client.get("/widgets", follow_redirects=False)
        assert after.status_code == 303


async def test_granting_a_permission_mid_session_takes_effect_immediately(
    session_factory,
) -> None:
    await _create_user_with_permissions(
        session_factory,
        email="operator@example.com",
        password="secret-password",
        permission_keys=("operations.access",),
    )
    app = _build_admin(session_factory).asgi()
    transport = httpx.ASGITransport(app=app)

    async with (
        _LifespanDriver(app),
        httpx.AsyncClient(transport=transport, base_url="http://localhost") as client,
    ):
        login = await client.post(
            "/auth/login",
            data={"identifier": "operator@example.com", "password": "secret-password"},
            follow_redirects=False,
        )
        client.cookies.set("rakit_session", login.cookies["rakit_session"])
        assert (await client.get("/widgets", follow_redirects=False)).status_code == 403

        async with session_factory() as session:
            role = (
                await session.execute(
                    select(Role)
                    .where(Role.name == "operator")
                    .options(selectinload(Role.permissions))
                )
            ).scalar_one()
            role.permissions.append(Permission(key="operations.resources.widgets.read"))
            await session.commit()

        assert (await client.get("/widgets")).status_code == 200
