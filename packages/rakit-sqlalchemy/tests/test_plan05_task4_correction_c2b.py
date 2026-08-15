"""Plan 05 Task 4 Correction C2B: sanctioned action -> SQLAlchemy mutation path."""

from collections.abc import AsyncIterator
from dataclasses import dataclass
from html.parser import HTMLParser
from typing import Any, cast
from urllib.parse import urlencode
from uuid import uuid4

import httpx
import pytest
from rakit_core.actions import ActionContext, ActionDefinition, ActionScope
from rakit_core.auth import Principal
from rakit_core.concurrency import (
    AttributeVersionProvider,
    ConcurrencyMode,
    ConcurrencyTokenService,
)
from rakit_core.config import SecretValue
from rakit_core.crypto import TokenService
from rakit_core.definitions import CompiledActionDefinition, RouteDefinition
from rakit_core.fields import FieldDefinition
from rakit_core.forms import FormSchema
from rakit_core.idempotency import IdempotencyReservation, IdempotencyStatus, OperationReceipt
from rakit_core.identity import IdentityCodec, RecordIdentity
from rakit_core.mutations import OperationAuthorization
from rakit_core.permissions import PermissionRequirement
from rakit_core.transactions import TransactionPolicy
from rakit_sqlalchemy.action_mutations import SQLAlchemyActionUpdateExecutor
from rakit_sqlalchemy.mutations import SQLAlchemyMutationService
from rakit_sqlalchemy.uow import SQLAlchemyOperationUnitOfWorkFactory
from rakit_web.action_routes import ActionBinding, build_action_routes
from rakit_web.resource_routes import build_templates
from sqlalchemy import event, select
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.sql.elements import ColumnElement
from starlette.applications import Starlette
from starlette.requests import Request


class Base(DeclarativeBase):
    pass


class Order(Base):
    __tablename__ = "c2b_action_orders"

    id: Mapped[int] = mapped_column(primary_key=True)
    version: Mapped[int] = mapped_column(default=1)
    status: Mapped[str]


_ACTION_PERMISSION = PermissionRequirement.all_of("ops.actions.approve.execute")
_PRINCIPAL = Principal(
    subject_id="operator",
    authenticated=True,
    permissions=frozenset(_ACTION_PERMISSION.permissions),
)


class _MemoryIdempotencyStore:
    def __init__(self) -> None:
        self._next = 1
        self._claims: dict[str, tuple[str, OperationReceipt | None]] = {}
        self._tokens: dict[int, str] = {}

    async def begin(self, token_hash: str, *, fingerprint: str) -> IdempotencyReservation:
        existing = self._claims.get(token_hash)
        if existing is not None:
            existing_fingerprint, receipt = existing
            if existing_fingerprint != fingerprint:
                raise ValueError("fingerprint mismatch")
            return IdempotencyReservation(
                reservation_id=1,
                status=(
                    IdempotencyStatus.COMPLETED
                    if receipt is not None
                    else IdempotencyStatus.IN_PROGRESS
                ),
                completed_receipt=receipt,
                claimed=False,
            )
        reservation = IdempotencyReservation(self._next, IdempotencyStatus.IN_PROGRESS)
        self._next += 1
        self._claims[token_hash] = (fingerprint, None)
        self._tokens[reservation.reservation_id] = token_hash
        return reservation

    async def complete(
        self, reservation: IdempotencyReservation, receipt: OperationReceipt
    ) -> None:
        token_hash = self._tokens[reservation.reservation_id]
        fingerprint, _ = self._claims[token_hash]
        self._claims[token_hash] = (fingerprint, receipt)

    async def release(self, reservation: IdempotencyReservation) -> None:
        token_hash = self._tokens.get(reservation.reservation_id)
        if token_hash is not None:
            self._claims.pop(token_hash, None)

    async def fail_final(self, reservation: IdempotencyReservation) -> None:
        return None


class _PrincipalMiddleware:
    def __init__(self, app: Any) -> None:
        self.app = app

    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        if scope["type"] == "http":
            scope.setdefault("state", {})["principal"] = _PRINCIPAL
        await self.app(scope, receive, send)


class _TokenParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.tokens: dict[str, str] = {}

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag != "input":
            return
        values = dict(attrs)
        name = values.get("name")
        value = values.get("value")
        if isinstance(name, str) and isinstance(value, str):
            self.tokens[name] = value


def _tokens(html: str) -> dict[str, str]:
    parser = _TokenParser()
    parser.feed(html)
    return parser.tokens


@dataclass
class _Harness:
    app: Any
    engine: AsyncEngine
    session_factory: async_sessionmaker[AsyncSession]
    mutation_service: SQLAlchemyMutationService
    identity: str


@pytest.fixture
async def harness(tmp_path: Any) -> AsyncIterator[_Harness]:
    database_path = tmp_path / "c2b-action.sqlite"
    engine = create_async_engine(f"sqlite+aiosqlite:///{database_path.as_posix()}")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as session:
        session.add(Order(id=1, version=1, status="draft"))
        await session.commit()

    token_service = TokenService.single_key(
        key_id="c2b",
        value=SecretValue("x" * 32),
        admin_id="ops",
    )
    mutation_service = SQLAlchemyMutationService(
        model=Order,
        session_factory=session_factory,
        form_schema=FormSchema(
            fields=(FieldDefinition(field_id="status", python_type=str, required=True),)
        ),
        writable_fields=("status",),
        identity_fields=("id",),
        token_service=token_service,
        concurrency_mode=ConcurrencyMode.REQUIRED,
        concurrency_provider=AttributeVersionProvider("version"),
        resource_id="orders",
    )

    def prepare(_context: ActionContext) -> dict[str, object]:
        return {"status": "approved"}

    executor = SQLAlchemyActionUpdateExecutor(
        mutation_service,
        prepare,
        message="Order approved",
    )
    definition = ActionDefinition(
        action_id="approve",
        label="Approve",
        scope=ActionScope.RECORD,
        resource_id="orders",
        permission=_ACTION_PERMISSION,
        executor=executor,
        mutating=True,
        transaction_policy=TransactionPolicy.AUTO,
        requires_concurrency=True,
    )
    compiled = CompiledActionDefinition(definition=definition, permission=_ACTION_PERMISSION)
    route = RouteDefinition(
        route_name="resource:orders:action:approve",
        methods=("GET", "POST"),
        path="/orders/{identity}/_actions/approve",
        owner_id="orders",
    )

    async def allow(_request: object) -> bool:
        return True

    async def authorize_action(
        _request: Request,
        _compiled: CompiledActionDefinition,
        identity: RecordIdentity | None,
    ) -> OperationAuthorization | None:
        return OperationAuthorization.for_requirement(
            admin_id="ops",
            resource_id="orders",
            operation="action:approve",
            principal_id="operator",
            requirement=_ACTION_PERMISSION,
            target_identity=identity,
        )

    binding = ActionBinding(
        routes=((route, compiled),),
        templates=build_templates(()),
        codec=IdentityCodec(),
        verify_csrf=allow,
        verify_submission_token=allow,
        issue_submission_token=lambda _request: uuid4().hex,
        authorize_action=authorize_action,
        load_record=mutation_service.get,
        record_version=lambda record: cast(Order, record).version,
        concurrency=ConcurrencyTokenService(token_service),
        concurrency_resource_id="orders",
        token_service=token_service,
        idempotency_store=_MemoryIdempotencyStore(),
        deadline_seconds=30,
        unit_of_work_factory=lambda: SQLAlchemyOperationUnitOfWorkFactory(session_factory),
    )
    app = _PrincipalMiddleware(Starlette(routes=build_action_routes(binding)))
    identity = IdentityCodec().encode(RecordIdentity(values={"id": 1}))

    try:
        yield _Harness(
            app=app,
            engine=engine,
            session_factory=session_factory,
            mutation_service=mutation_service,
            identity=identity,
        )
    finally:
        await engine.dispose()


async def _open_action(client: httpx.AsyncClient, identity: str) -> dict[str, str]:
    response = await client.get(f"/orders/{identity}/_actions/approve")
    assert response.status_code == 200
    tokens = _tokens(response.text)
    assert "submission_token" in tokens
    assert "concurrency_token" in tokens
    return tokens


async def _stored_order(factory: async_sessionmaker[AsyncSession]) -> Order:
    async with factory() as session:
        return cast(Order, await session.scalar(select(Order).where(Order.id == 1)))


@pytest.mark.anyio
async def test_action_permission_updates_atomically_in_the_root_uow(harness: _Harness) -> None:
    commits = 0

    def record_commit(_connection: object) -> None:
        nonlocal commits
        commits += 1

    event.listen(harness.engine.sync_engine, "commit", record_commit)
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=harness.app),
            base_url="http://test",
        ) as client:
            tokens = await _open_action(client, harness.identity)
            response = await client.post(
                f"/orders/{harness.identity}/_actions/approve",
                content=urlencode(
                    [
                        ("csrf_token", "csrf"),
                        ("submission_token", tokens["submission_token"]),
                        ("concurrency_token", tokens["concurrency_token"]),
                    ]
                ),
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                follow_redirects=False,
            )
    finally:
        event.remove(harness.engine.sync_engine, "commit", record_commit)

    assert response.status_code == 303
    assert commits == 1
    stored = await _stored_order(harness.session_factory)
    assert (stored.status, stored.version) == ("approved", 2)
    assert _PRINCIPAL.permissions == frozenset({"ops.actions.approve.execute"})
    assert "ops.resources.orders.update" not in _PRINCIPAL.permissions


@pytest.mark.anyio
async def test_atomic_write_predicate_can_reject_after_web_precheck(
    harness: _Harness,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_conditions = harness.mutation_service._concurrency_conditions

    def impossible_write_condition(record: object) -> tuple[ColumnElement[bool], ...]:
        return (
            *original_conditions(record),
            Order.version == 999,
        )

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=harness.app),
        base_url="http://test",
    ) as client:
        tokens = await _open_action(client, harness.identity)
        # The signed token and the freshly loaded web record still agree here.
        # Only the SQL write predicate below is made impossible, proving that
        # the sanctioned executor does not treat B2B2's precheck as the durable
        # concurrency guarantee.
        monkeypatch.setattr(
            harness.mutation_service,
            "_concurrency_conditions",
            impossible_write_condition,
        )
        response = await client.post(
            f"/orders/{harness.identity}/_actions/approve",
            content=urlencode(
                [
                    ("csrf_token", "csrf"),
                    ("submission_token", tokens["submission_token"]),
                    ("concurrency_token", tokens["concurrency_token"]),
                ]
            ),
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            follow_redirects=False,
        )

    assert response.status_code == 409
    stored = await _stored_order(harness.session_factory)
    assert (stored.status, stored.version) == ("draft", 1)
