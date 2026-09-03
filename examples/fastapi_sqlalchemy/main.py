"""FastAPI host composed with a SQLAlchemy-backed Rakit admin at ``/admin``."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from rakit import Admin, ModelAdmin, SecretValue, compose_asgi
from rakit.sqlalchemy import SQLAlchemyPlugin
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.pool import StaticPool


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "example_users"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str]
    email: Mapped[str]


class UserAdmin(ModelAdmin):
    model = User
    resource_id = "users"
    path = "/users"
    label = "Users"
    singular_label = "User"
    list_fields = ("id", "name", "email")
    detail_fields = ("id", "name", "email")
    filter_fields = ("id", "name", "email")
    search_fields = ("name", "email")
    sort_fields = ("id", "name", "email")


# The host application owns this engine. The current public plugin API receives only a
# session factory, so FastAPI's lifespan performs disposal (the owned=False intent) rather
# than asking Rakit to manage an application-owned resource.
engine = create_async_engine(
    "sqlite+aiosqlite:///:memory:",
    poolclass=StaticPool,
)
session_factory = async_sessionmaker(engine, expire_on_commit=False)

admin = Admin(
    admin_id="operations",
    title="Operations",
    debug=False,
    secret_key=SecretValue("example-only-change-me-000000000"),
)
admin.install(SQLAlchemyPlugin(session_factory=session_factory))
admin.register(UserAdmin)


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    async with session_factory() as session:
        await session.execute(delete(User))
        session.add_all(
            [
                User(id=1, name="Ada", email="ada@example.com"),
                User(id=2, name="Grace", email="grace@work.test"),
            ]
        )
        await session.commit()
    try:
        yield
    finally:
        await engine.dispose()


host = FastAPI(lifespan=lifespan)
app = compose_asgi(host, admin, path="/admin")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8000)
