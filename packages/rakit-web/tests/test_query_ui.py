from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx
import pytest
from conftest import LifespanDriver
from rakit import Admin, ModelAdmin, SecretValue
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
    email: Mapped[str]


class UserAdmin(ModelAdmin):
    model = User
    resource_id = "users"
    path = "/users"
    label = "Users"
    singular_label = "User"


async def _seeded_factory() -> tuple[async_sessionmaker[AsyncSession], AsyncEngine]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        session.add_all(
            [
                User(id=1, name="Ada", email="ada@example.com"),
                User(id=2, name="Grace", email="grace@work.test"),
            ]
        )
        await session.commit()
    return factory, engine


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
async def client() -> AsyncIterator[httpx.AsyncClient]:
    factory, engine = await _seeded_factory()
    admin = Admin(
        admin_id="operations",
        title="Operations",
        debug=False,
        secret_key=SecretValue("x" * 32),
    )
    admin.install(SQLAlchemyPlugin(session_factory=factory))
    admin.register(UserAdmin)
    async with _client_for(admin) as http_client:
        yield http_client
    await engine.dispose()


async def test_deferred_count_has_separate_fragment(client: httpx.AsyncClient) -> None:
    page = await client.get("/users?count_policy=deferred")
    assert "Calculating total" in page.text
    count = await client.get("/users/_count", headers={"HX-Request": "true"})
    assert count.text.strip() == "2"


async def test_exact_count_renders_total_inline(client: httpx.AsyncClient) -> None:
    page = await client.get("/users")
    assert "2 total" in page.text
    assert "Calculating total" not in page.text


async def test_deferred_count_fragment_respects_search(client: httpx.AsyncClient) -> None:
    count = await client.get(
        "/users/_count", params={"search": "work"}, headers={"HX-Request": "true"}
    )
    assert count.text.strip() == "1"
    assert count.headers["cache-control"] == "no-store"


async def test_filter_via_url_param(client: httpx.AsyncClient) -> None:
    response = await client.get("/users", params={"filter": "name:eq:Ada"})
    assert response.status_code == 200
    assert "Ada" in response.text
    assert "Grace" not in response.text


async def test_search_via_url_param(client: httpx.AsyncClient) -> None:
    response = await client.get("/users", params={"search": "work"})
    assert response.status_code == 200
    assert "Grace" in response.text
    assert "Ada" not in response.text


async def test_per_page_over_max_falls_back_to_default(client: httpx.AsyncClient) -> None:
    # per_page=99999 violates OffsetPagination's le=200 bound; parse_query must
    # not let it through -- it falls back to the default query (both rows fit).
    response = await client.get("/users", params={"per_page": "99999"})
    assert response.status_code == 200
    assert "Ada" in response.text
    assert "Grace" in response.text


async def test_sort_header_link_omits_page(client: httpx.AsyncClient) -> None:
    response = await client.get("/users", params={"page": "1", "sort": "name"})
    # Sort-toggle links reset pagination: they never carry a page param forward.
    assert "sort=-name" in response.text
    assert "page=" not in response.text
