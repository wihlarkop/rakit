from rakit_core.definitions import ResourceFieldPolicy
from rakit_sqlalchemy.datasource import SQLAlchemyDataSource
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Account(Base):
    __tablename__ = "generated_api_accounts"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str]
    nickname: Mapped[str | None] = mapped_column(nullable=True)
    status: Mapped[str] = mapped_column(server_default=text("'active'"))
    password_hash: Mapped[str]


def test_sqlalchemy_datasource_exposes_neutral_generated_field_definitions() -> None:
    datasource = SQLAlchemyDataSource(
        model=Account,
        session_factory=async_sessionmaker[AsyncSession](),
        field_policy=ResourceFieldPolicy(
            list_fields=("id", "email"),
            detail_fields=("id", "email", "nickname", "status"),
            filter_fields=("status",),
            search_fields=("email",),
            sort_fields=("email",),
        ),
    )

    fields = {field.field_id: field for field in datasource.field_definitions}

    assert fields["id"].python_type is int
    assert fields["id"].writable is False
    assert fields["id"].required is False

    assert fields["email"].python_type is str
    assert fields["email"].writable is True
    assert fields["email"].required is True
    assert fields["email"].nullable is False

    assert fields["nickname"].nullable is True
    assert fields["nickname"].required is False

    assert fields["status"].required is False
    assert fields["status"].filterable is True

    assert fields["password_hash"].sensitive is True
    assert fields["password_hash"].readable is False
    assert fields["password_hash"].writable is False
