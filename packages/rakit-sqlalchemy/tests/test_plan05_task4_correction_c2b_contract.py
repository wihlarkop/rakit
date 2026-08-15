"""C2B capability guardrails for the sanctioned SQLAlchemy action executor."""

import pytest
from rakit.sqlalchemy import SQLAlchemyActionUpdateExecutor as PublicActionUpdateExecutor
from rakit_core.concurrency import ConcurrencyMode, SnapshotVersionProvider
from rakit_core.config import SecretValue
from rakit_core.crypto import TokenService
from rakit_core.fields import FieldDefinition
from rakit_core.forms import FormSchema
from rakit_sqlalchemy.action_mutations import SQLAlchemyActionUpdateExecutor
from rakit_sqlalchemy.mutations import SQLAlchemyMutationService
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Order(Base):
    __tablename__ = "c2b_contract_orders"

    id: Mapped[int] = mapped_column(primary_key=True)
    version: Mapped[int] = mapped_column(default=1)
    status: Mapped[str]


def test_sanctioned_executor_is_public_sqlalchemy_api() -> None:
    assert PublicActionUpdateExecutor is SQLAlchemyActionUpdateExecutor


def test_snapshot_provider_cannot_claim_atomic_action_concurrency() -> None:
    session_factory = async_sessionmaker[AsyncSession]()
    token_service = TokenService.single_key(
        key_id="c2b-contract",
        value=SecretValue("x" * 32),
        admin_id="ops",
    )
    service = SQLAlchemyMutationService(
        model=Order,
        session_factory=session_factory,
        form_schema=FormSchema(
            fields=(FieldDefinition(field_id="status", python_type=str, required=True),)
        ),
        writable_fields=("status",),
        identity_fields=("id",),
        token_service=token_service,
        concurrency_mode=ConcurrencyMode.REQUIRED,
        concurrency_provider=SnapshotVersionProvider(fields=("version",)),
        resource_id="orders",
    )

    with pytest.raises(ValueError, match="atomically advanceable"):
        SQLAlchemyActionUpdateExecutor(
            service,
            lambda _context: {"status": "approved"},
        )
