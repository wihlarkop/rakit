from __future__ import annotations

from collections.abc import Mapping
from urllib.parse import urlencode

import httpx
import pytest
from rakit_core.auth import Principal
from rakit_core.concurrency import ConcurrencyTokenService
from rakit_core.config import SecretValue
from rakit_core.crypto import TokenService
from rakit_core.definitions import ResourceFieldPolicy
from rakit_core.errors import ErrorCode, RakitError
from rakit_core.fields import FieldDefinition
from rakit_core.forms import FormSchema
from rakit_core.idempotency import IdempotencyReservation, IdempotencyStatus, OperationReceipt
from rakit_core.identity import RecordIdentity
from rakit_core.mutations import (
    MutationAuthorization,
    OperationAuthorization,
    OperationAuthorizationSet,
)
from rakit_core.operations import CancellationContext, OperationContext, activate_operation_context
from rakit_core.permissions import PermissionRequirement
from rakit_core.relationship_mutations import RelationshipChangePlan, UpdateRelated
from rakit_core.relationships import (
    CompiledRelationship,
    RelationshipCardinality,
    RelationshipDefinition,
    RelationshipEditMode,
    RelationshipKind,
)
from rakit_core.resources import ResourceService
from rakit_sqlalchemy.core_concurrency import MappingVersionProvider
from rakit_sqlalchemy.core_datasource import SQLAlchemyCoreDataSource
from rakit_sqlalchemy.core_relationship_mutations import SQLAlchemyCoreRelationshipMutationService
from rakit_sqlalchemy.core_write import SQLAlchemyCoreMutationService
from rakit_web.form_routes import WriteResourceBinding, build_write_routes
from rakit_web.relationship_routes import (
    RelationshipEditorBinding,
    RelationshipFormBinding,
    relationship_prefix,
)
from rakit_web.resource_routes import build_templates
from sqlalchemy import Column, ForeignKey, Integer, MetaData, String, Table, select, update
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from starlette.applications import Starlette
from starlette.types import ASGIApp, Receive, Scope, Send

ROOT_REQUIREMENT = PermissionRequirement.all_of("admin.resources.orders.update")
RELATIONSHIP_REQUIREMENT = PermissionRequirement.all_of(
    "admin.resources.orders.relationships.customer.update"
)
PRINCIPAL = Principal(subject_id="tester", authenticated=True)


class MemoryIdempotencyStore:
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
        self._tokens[reservation.reservation_id] = token_hash
        self._claims[token_hash] = (fingerprint, None)
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
        del reservation


class PrincipalMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http":
            state = scope.setdefault("state", {})
            assert isinstance(state, dict)
            state["principal"] = PRINCIPAL
            state["request_id"] = "core-public-graph-test"
        await self.app(scope, receive, send)


def _token_service() -> TokenService:
    return TokenService.single_key(
        key_id="test",
        value=SecretValue("core-public-graph-write-secret-value"),
        admin_id="admin",
    )


def _source(table: Table, engine: AsyncEngine) -> SQLAlchemyCoreDataSource:
    fields = tuple(column.key for column in table.columns)
    return SQLAlchemyCoreDataSource(
        table=table,
        engine=engine,
        field_policy=ResourceFieldPolicy(list_fields=fields, detail_fields=fields),
    )


async def _allow(_request: object) -> bool:
    return True


async def _mutation_authorizer(
    _request: object, operation: str, identity: RecordIdentity | None
) -> MutationAuthorization:
    return MutationAuthorization.for_requirement(
        admin_id="admin",
        resource_id="orders",
        operation=operation,
        principal_id="tester",
        requirement=ROOT_REQUIREMENT,
        target_identity=identity,
    )


async def _graph_authorizer(
    _request: object,
    root: MutationAuthorization,
    parent_identity: RecordIdentity | None,
    changes: tuple[object, ...],
) -> OperationAuthorizationSet:
    capabilities = []
    for raw_change in changes:
        if not isinstance(raw_change, RelationshipChangePlan):
            raise TypeError("test graph authorizer received a non-relationship change")
        change = raw_change
        capabilities.append(
            OperationAuthorization.for_requirement(
                admin_id="admin",
                resource_id="orders",
                operation=change.operation_id,
                principal_id="tester",
                requirement=RELATIONSHIP_REQUIREMENT,
                target_identity=parent_identity,
            )
        )
    return OperationAuthorizationSet(root=root, capabilities=tuple(capabilities))


def _tables() -> tuple[MetaData, Table, Table]:
    metadata = MetaData()
    customers = Table(
        "core_public_customers",
        metadata,
        Column("id", Integer, primary_key=True),
        Column("name", String(100), nullable=False),
    )
    orders = Table(
        "core_public_orders",
        metadata,
        Column("id", Integer, primary_key=True),
        Column("version", Integer, nullable=False),
        Column("status", String(100), nullable=False),
        Column("customer_id", ForeignKey(customers.c.id), nullable=True),
    )
    return metadata, customers, orders


async def _runtime() -> tuple[
    AsyncEngine,
    Table,
    Table,
    SQLAlchemyCoreMutationService,
    SQLAlchemyCoreRelationshipMutationService,
    WriteResourceBinding,
]:
    metadata, customers, orders = _tables()
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    parent_source = _source(orders, engine)
    target_source = _source(customers, engine)
    definition = RelationshipDefinition(
        relationship_id="customer",
        target_resource_id="customers",
        label="Customer",
        kind=RelationshipKind.MANY_TO_ONE,
        cardinality=RelationshipCardinality.TO_ONE,
        nullable=True,
        edit_mode=RelationshipEditMode.LINK,
        writable=True,
        record_label_field="name",
    )
    parent_source.validate_relationship(definition, target_source)
    relationship = CompiledRelationship(
        source_resource_id="orders",
        definition=definition,
        mutation_permission=RELATIONSHIP_REQUIREMENT,
        target_delete_permission=None,
        route_path="/orders/{identity}/_relationships/customer",
    )
    tokens = ConcurrencyTokenService(_token_service())
    relationship_service = SQLAlchemyCoreRelationshipMutationService(
        parent_data_source=parent_source,
        relationships=(relationship,),
        target_data_sources={"customers": target_source},
        concurrency_provider=MappingVersionProvider("version"),
        concurrency_tokens=tokens,
    )
    form_schema = FormSchema(
        fields=(FieldDefinition(field_id="status", python_type=str, required=True),)
    )
    writer = SQLAlchemyCoreMutationService(
        resource_id="orders",
        data_source=parent_source,
        engine=engine,
        form_schema=form_schema,
        writable_fields=("status",),
        token_service=_token_service(),
        version_field="version",
    )
    store = MemoryIdempotencyStore()
    writer.bind_graph_relationship_service(relationship_service, idempotency_store=store)
    editor = RelationshipEditorBinding(
        relationship=relationship,
        target_service=ResourceService(target_source),
        state_provider=relationship_service,
    )
    binding = WriteResourceBinding(
        path="/orders",
        label="Order",
        form_schema=form_schema,
        mutation_service=writer,
        templates=build_templates(()),
        authorize=_allow,
        verify_csrf=_allow,
        verify_submission_token=_allow,
        issue_submission_token=lambda _request: "submission-1",
        resource_id="orders",
        deadline_seconds=1.0,
        idempotency_store=store,
        mutation_authorizer=_mutation_authorizer,
        graph_mutation_authorizer=_graph_authorizer,
        relationship_form=RelationshipFormBinding(editors=(editor,)),
    )
    async with engine.begin() as connection:
        await connection.run_sync(metadata.create_all)
        await connection.execute(
            customers.insert(),
            ({"id": 1, "name": "Ada"}, {"id": 2, "name": "Grace"}),
        )
        await connection.execute(
            orders.insert().values(id=1, version=1, status="draft", customer_id=1)
        )
    return engine, customers, orders, writer, relationship_service, binding


def _client(binding: WriteResourceBinding) -> httpx.AsyncClient:
    app = Starlette(routes=build_write_routes(binding))
    transport = httpx.ASGITransport(app=PrincipalMiddleware(app), raise_app_exceptions=False)
    return httpx.AsyncClient(transport=transport, base_url="http://testserver")


@pytest.mark.anyio
async def test_core_mapping_record_populates_public_edit_form() -> None:
    engine, _customers, _orders, _writer, _relationship_service, binding = await _runtime()
    try:
        encoded = binding.codec.encode(RecordIdentity(values={"id": 1}))
        async with _client(binding) as client:
            response = await client.get(f"/orders/{encoded}/edit")
        assert response.status_code == 200
        assert 'name="status"' in response.text
        assert 'value="draft"' in response.text
    finally:
        await engine.dispose()


@pytest.mark.anyio
async def test_core_public_form_graph_update_claims_parent_once_and_commits_relationship() -> None:
    engine, _customers, orders, writer, relationship_service, binding = await _runtime()
    parent = RecordIdentity(values={"id": 1})
    target = RecordIdentity(values={"id": 2})
    try:
        encoded_parent = binding.codec.encode(parent)
        encoded_target = binding.codec.encode(target)
        current = await writer.get(parent)
        assert isinstance(current, Mapping)
        parent_token = writer.issue_update_token(current)
        relationship_token = await relationship_service.issue_concurrency_token(parent, "customer")
        prefix = relationship_prefix("customer")
        payload = urlencode(
            {
                "status": "confirmed",
                "submission_token": "submission-graph-1",
                "concurrency_token": parent_token,
                f"{prefix}set": encoded_target,
                f"{prefix}concurrency": relationship_token,
            }
        )
        async with _client(binding) as client:
            response = await client.post(
                f"/orders/{encoded_parent}/edit",
                content=payload,
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                follow_redirects=False,
            )
        assert response.status_code == 303
        async with engine.connect() as connection:
            row = (await connection.execute(select(orders))).mappings().one()
        assert dict(row) == {
            "id": 1,
            "version": 2,
            "status": "confirmed",
            "customer_id": 2,
        }
    finally:
        await engine.dispose()


@pytest.mark.anyio
async def test_core_public_graph_stale_relationship_proof_rolls_back_scalar_change() -> None:
    engine, _customers, orders, writer, relationship_service, binding = await _runtime()
    parent = RecordIdentity(values={"id": 1})
    target = RecordIdentity(values={"id": 1})
    try:
        encoded_parent = binding.codec.encode(parent)
        encoded_target = binding.codec.encode(target)
        current = await writer.get(parent)
        assert isinstance(current, Mapping)
        parent_token = writer.issue_update_token(current)
        stale_relationship_token = await relationship_service.issue_concurrency_token(
            parent, "customer"
        )
        async with engine.begin() as connection:
            await connection.execute(update(orders).where(orders.c.id == 1).values(customer_id=2))
        prefix = relationship_prefix("customer")
        payload = urlencode(
            {
                "status": "must-not-persist",
                "submission_token": "submission-graph-stale",
                "concurrency_token": parent_token,
                f"{prefix}set": encoded_target,
                f"{prefix}concurrency": stale_relationship_token,
            }
        )
        async with _client(binding) as client:
            response = await client.post(
                f"/orders/{encoded_parent}/edit",
                content=payload,
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                follow_redirects=False,
            )
        assert response.status_code == 409
        async with engine.connect() as connection:
            row = (await connection.execute(select(orders))).mappings().one()
        assert dict(row) == {
            "id": 1,
            "version": 1,
            "status": "draft",
            "customer_id": 2,
        }
    finally:
        await engine.dispose()


@pytest.mark.anyio
async def test_core_graph_child_mutation_requires_exact_target_capability_before_execution() -> (
    None
):
    engine, _customers, _orders, writer, _relationship_service, _binding = await _runtime()
    parent = RecordIdentity(values={"id": 1})
    root = await _mutation_authorizer(None, "update", parent)
    change = RelationshipChangePlan(
        operation_id="relationship:orders:customer:update",
        relationship_id="customer",
        steps=(UpdateRelated(identity=RecordIdentity(values={"id": 2}), values={"name": "new"}),),
        authorization_requirement=RELATIONSHIP_REQUIREMENT,
        concurrency_token="relationship-token",
    )
    context = OperationContext(
        deadline=None,
        cancellation=CancellationContext(),
        principal=PRINCIPAL,
        principal_id="tester",
        admin_id="admin",
        resource_id="orders",
        operation="update",
        permissions=root.permissions,
        permission_requirement=root.requirement,
    )
    try:
        with activate_operation_context(context), pytest.raises(RakitError) as raised:
            await writer.update_graph(
                parent,
                {"status": "confirmed"},
                relationship_changes=(change,),
                concurrency_token=None,
                authorizations=OperationAuthorizationSet(
                    root=root,
                    capabilities=(
                        OperationAuthorization.for_requirement(
                            admin_id="admin",
                            resource_id="orders",
                            operation=change.operation_id,
                            principal_id="tester",
                            requirement=RELATIONSHIP_REQUIREMENT,
                            target_identity=parent,
                        ),
                    ),
                ),
            )
        assert raised.value.code == ErrorCode.AUTH_FORBIDDEN
    finally:
        await engine.dispose()
