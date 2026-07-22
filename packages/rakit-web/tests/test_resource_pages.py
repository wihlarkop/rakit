import importlib
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
import pytest
from conftest import LifespanDriver
from rakit import Admin, ModelAdmin, SecretValue
from rakit_core.identity import IdentityCodec, RecordIdentity
from rakit_sqlalchemy.plugin import SQLAlchemyPlugin
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str]


class UserAdmin(ModelAdmin):
    model = User
    resource_id = "users"
    path = "/users"
    label = "Users"
    singular_label = "User"


async def _seeded_session_factory() -> tuple[async_sessionmaker[AsyncSession], AsyncEngine]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        session.add_all([User(id=1, name="Ada"), User(id=2, name="Grace")])
        await session.commit()
    return factory, engine


def _build_admin(
    factory: async_sessionmaker[AsyncSession],
    template_dirs: tuple[Path, ...] = (),
) -> Admin:
    admin = Admin(
        admin_id="operations",
        title="Operations",
        debug=False,
        secret_key=SecretValue("x" * 32),
        template_dirs=template_dirs,
    )
    admin.install(SQLAlchemyPlugin(session_factory=factory))
    admin.register(UserAdmin)
    return admin


@asynccontextmanager
async def _client_for(admin: Admin) -> AsyncIterator[httpx.AsyncClient]:
    app = admin.asgi()
    transport = httpx.ASGITransport(app=app)
    async with (
        LifespanDriver(app),
        httpx.AsyncClient(transport=transport, base_url="http://testserver") as http_client,
    ):
        yield http_client


@pytest.fixture
async def resource_client() -> AsyncIterator[httpx.AsyncClient]:
    factory, engine = await _seeded_session_factory()
    admin = _build_admin(factory)
    async with _client_for(admin) as http_client:
        yield http_client
    await engine.dispose()


async def test_list_full_page_and_fragment(resource_client) -> None:
    full = await resource_client.get("/users")
    fragment = await resource_client.get("/users", headers={"HX-Request": "true"})

    assert full.status_code == 200
    assert "<html" in full.text
    assert "Ada" in full.text
    assert full.headers["cache-control"] == "no-store"

    assert fragment.status_code == 200
    assert "<html" not in fragment.text
    assert 'data-rakit-resource="users"' in fragment.text
    assert "Ada" in fragment.text
    assert fragment.headers["cache-control"] == "no-store"


async def test_full_page_references_only_local_hashed_assets(resource_client) -> None:
    static_url = importlib.import_module("rakit_web.assets").static_url
    response = await resource_client.get("/users")

    assert static_url("rakit.css") in response.text
    assert static_url("htmx.min.js") in response.text
    assert 'src="http://' not in response.text
    assert 'src="https://' not in response.text
    assert 'href="https://' not in response.text


async def test_detail_page_renders_record(resource_client) -> None:
    encoded = IdentityCodec().encode(RecordIdentity(values={"id": 1}))
    response = await resource_client.get(f"/users/{encoded}")

    assert response.status_code == 200
    assert "<html" in response.text
    assert "Ada" in response.text
    assert response.headers["cache-control"] == "no-store"


async def test_detail_page_unknown_identity_returns_404(resource_client) -> None:
    encoded = IdentityCodec().encode(RecordIdentity(values={"id": 999}))
    response = await resource_client.get(f"/users/{encoded}")

    assert response.status_code == 404


async def test_resource_specific_user_override_wins(tmp_path: Path) -> None:
    override_dir = tmp_path / "resources" / "users"
    override_dir.mkdir(parents=True)
    (override_dir / "list.html").write_text(
        '{% extends "base.html" %}{% block content %}'
        '<p data-override="resource-specific">users override</p>'
        "{% endblock %}",
        encoding="utf-8",
    )

    factory, engine = await _seeded_session_factory()
    admin = _build_admin(factory, template_dirs=(tmp_path,))
    async with _client_for(admin) as http_client:
        response = await http_client.get("/users")
    await engine.dispose()

    assert response.status_code == 200
    assert 'data-override="resource-specific"' in response.text


async def test_generic_user_override_wins_over_builtin(tmp_path: Path) -> None:
    override_dir = tmp_path / "resources"
    override_dir.mkdir(parents=True)
    (override_dir / "list.html").write_text(
        '{% extends "base.html" %}{% block content %}'
        '<p data-override="generic">generic override</p>'
        "{% endblock %}",
        encoding="utf-8",
    )

    factory, engine = await _seeded_session_factory()
    admin = _build_admin(factory, template_dirs=(tmp_path,))
    async with _client_for(admin) as http_client:
        response = await http_client.get("/users")
    await engine.dispose()

    assert response.status_code == 200
    assert 'data-override="generic"' in response.text
