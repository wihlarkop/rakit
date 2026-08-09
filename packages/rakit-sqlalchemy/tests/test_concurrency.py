from collections.abc import AsyncIterator

import pytest
from rakit_core.config import SecretValue
from rakit_core.crypto import TokenService
from rakit_core.errors import ErrorCode, RakitError
from rakit_core.fields import FieldDefinition
from rakit_core.forms import FormSchema
from rakit_sqlalchemy.mutations import SQLAlchemyMutationService
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "concurrency_users"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str]
    revision: Mapped[int] = mapped_column(default=1)


@pytest.fixture
async def session_factory() -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    yield async_sessionmaker(engine, expire_on_commit=False)
    await engine.dispose()


@pytest.mark.anyio
async def test_stale_update_returns_a_conflict_before_writing(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    service = SQLAlchemyMutationService(
        model=User,
        session_factory=session_factory,
        form_schema=FormSchema(
            fields=(FieldDefinition(field_id="name", python_type=str, required=True),)
        ),
        writable_fields=("name",),
        identity_fields=("id",),
        token_service=TokenService.single_key(
            key_id="test", value=SecretValue("x" * 32), admin_id="admin"
        ),
        version_field="revision",
    )
    created = await service.create({"name": "Ada"})
    token = service.issue_update_token(created.record)

    await service.update(created.identity, {"name": "Grace"}, concurrency_token=token)

    with pytest.raises(RakitError) as caught:
        await service.update(created.identity, {"name": "Ada"}, concurrency_token=token)
    assert caught.value.code == ErrorCode.RESOURCE_CONFLICT
    assert caught.value.status_code == 409
