"""Real ASGI + SQLAlchemy + file-backed SQLite integration fixture for Plan 05 Phase 3B.

Every HTTP request in this suite goes through the real Rakit web routes into the
real SQLAlchemy mutation services and a real file-backed database.  Only the
request authorization boundary and the in-memory idempotency store are test
helpers; no mutation service is mocked for the core proofs.
"""

from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass
from html.parser import HTMLParser
from typing import Any, cast
from urllib.parse import urlencode
from uuid import uuid4

import httpx
import pytest
from rakit_core.actions import (
    ActionAvailabilityDecision,
    ActionContext,
    ActionDefinition,
    ActionScope,
    ActionSuccess,
    PreparedMutationExecutor,
)
from rakit_core.auth import Principal
from rakit_core.concurrency import AttributeVersionProvider, ConcurrencyTokenService
from rakit_core.config import SecretValue
from rakit_core.crypto import TokenService
from rakit_core.definitions import (
    CompiledActionDefinition,
    ResourceFieldPolicy,
    RouteDefinition,
)
from rakit_core.fields import FieldDefinition
from rakit_core.forms import FieldLayout, FormLayout, FormSchema, RelationshipPanel
from rakit_core.idempotency import IdempotencyReservation, IdempotencyStatus, OperationReceipt
from rakit_core.identity import IdentityCodec, RecordIdentity
from rakit_core.mutations import (
    MutationAuthorization,
    MutationHooks,
    OperationAuthorization,
    OperationAuthorizationSet,
)
from rakit_core.operations import OperationExecutorCapabilities
from rakit_core.permissions import PermissionRequirement
from rakit_core.relationship_mutations import (
    CreateRelated,
    DeleteRelated,
    UpdateRelated,
)
from rakit_core.relationships import (
    CompiledRelationship,
    RelationshipCardinality,
    RelationshipDefinition,
    RelationshipDestructivePolicy,
    RelationshipEditMode,
    RelationshipKind,
    RelationshipOrderingDefinition,
)
from rakit_core.resources import ResourceService
from rakit_core.transactions import TransactionPolicy
from rakit_sqlalchemy.datasource import SQLAlchemyDataSource
from rakit_sqlalchemy.mutations import SQLAlchemyMutationService
from rakit_sqlalchemy.relationship_mutations import SQLAlchemyRelationshipMutationService
from rakit_sqlalchemy.uow import SQLAlchemyOperationUnitOfWorkFactory
from rakit_web.action_routes import ActionBinding, build_action_routes
from rakit_web.assets import static_files
from rakit_web.form_routes import WriteResourceBinding, build_write_routes
from rakit_web.relationship_routes import (
    RelationshipEditorBinding,
    RelationshipFormBinding,
    build_relationship_routes,
    relationship_prefix,  # noqa: F401  (re-exported for integration tests)
)
from rakit_web.resource_routes import build_templates
from sqlalchemy import Column, ForeignKey, Table, event, select
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.routing import Mount


class Base(DeclarativeBase):
    pass


class Customer(Base):
    __tablename__ = "integration_customers"

    id: Mapped[int] = mapped_column(primary_key=True)
    version: Mapped[int] = mapped_column(default=1)
    name: Mapped[str]
    enabled: Mapped[bool] = mapped_column(default=True)


class Tag(Base):
    __tablename__ = "integration_tags"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str]


order_tags = Table(
    "integration_order_tags",
    Base.metadata,
    Column("order_id", ForeignKey("integration_orders.id"), primary_key=True),
    Column("tag_id", ForeignKey("integration_tags.id"), primary_key=True),
)


class Course(Base):
    __tablename__ = "integration_courses"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str]


class LineItem(Base):
    __tablename__ = "integration_line_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    version: Mapped[int] = mapped_column(default=1)
    order_id: Mapped[int] = mapped_column(ForeignKey("integration_orders.id"), nullable=False)
    sku: Mapped[str]
    quantity: Mapped[int]
    position: Mapped[int] = mapped_column(nullable=False, default=0)
    order: Mapped["Order"] = relationship(back_populates="line_items")


class Attachment(Base):
    __tablename__ = "integration_attachments"

    id: Mapped[int] = mapped_column(primary_key=True)
    version: Mapped[int] = mapped_column(default=1)
    order_id: Mapped[int | None] = mapped_column(ForeignKey("integration_orders.id"))
    name: Mapped[str]
    order: Mapped["Order"] = relationship(back_populates="attachments")


class Enrollment(Base):
    __tablename__ = "integration_enrollments"

    id: Mapped[int] = mapped_column(primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("integration_orders.id"), nullable=False)
    course_id: Mapped[int] = mapped_column(ForeignKey("integration_courses.id"), nullable=False)
    grade: Mapped[str]
    order: Mapped["Order"] = relationship(back_populates="enrollments")
    course: Mapped[Course] = relationship()


class Order(Base):
    __tablename__ = "integration_orders"

    id: Mapped[int] = mapped_column(primary_key=True)
    version: Mapped[int] = mapped_column(default=1)
    status: Mapped[str]
    customer_id: Mapped[int | None] = mapped_column(ForeignKey("integration_customers.id"))
    customer: Mapped[Customer | None] = relationship()
    tags: Mapped[list[Tag]] = relationship(secondary=order_tags)
    line_items: Mapped[list[LineItem]] = relationship(
        back_populates="order", order_by="LineItem.position"
    )
    enrollments: Mapped[list[Enrollment]] = relationship(
        back_populates="order", cascade="all, delete-orphan"
    )
    attachments: Mapped[list[Attachment]] = relationship(back_populates="order")


class MemoryIdempotencyStore:
    """Durable-receipt-shaped in-memory store mirroring the repository test fixture."""

    def __init__(self) -> None:
        self.claims: dict[str, tuple[str, OperationReceipt | None]] = {}
        self._tokens: dict[int, str] = {}
        self._next = 1

    async def begin(self, token_hash: str, *, fingerprint: str) -> IdempotencyReservation:
        existing = self.claims.get(token_hash)
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
        self.claims[token_hash] = (fingerprint, None)
        return reservation

    async def complete(
        self, reservation: IdempotencyReservation, receipt: OperationReceipt
    ) -> None:
        key = self._tokens[reservation.reservation_id]
        fingerprint, _ = self.claims[key]
        self.claims[key] = (fingerprint, receipt)

    async def release(self, reservation: IdempotencyReservation) -> None:
        key = self._tokens.get(reservation.reservation_id)
        if key is not None:
            self.claims.pop(key, None)

    async def fail_final(self, reservation: IdempotencyReservation) -> None:
        return None


_REQ_ORDERS_UPDATE = PermissionRequirement.all_of("integration.orders.update")
_REQ_LINE_CREATE = PermissionRequirement.all_of("integration.line_items.create")
_REQ_LINE_UPDATE = PermissionRequirement.all_of("integration.line_items.update")
_REQ_LINE_DELETE = PermissionRequirement.all_of("integration.line_items.delete")

_ADMIN_ID = "integration"
_PRINCIPAL_ID = "tester"


class _IntegrationAtomicPreparedMutationExecutor(PreparedMutationExecutor):
    # Test-only bridge. Production PreparedMutationExecutor deliberately keeps
    # atomic_concurrency=False until C2B introduces the sanctioned public path.
    capabilities = OperationExecutorCapabilities(
        participates_in_uow=True,
        atomic_concurrency=True,
    )


class RenderedFormParser(HTMLParser):
    """Collect successful controls from the rendered parent form like a browser."""

    def __init__(self) -> None:
        super().__init__()
        self.controls: list[tuple[str, str]] = []
        self._form_depth = 0
        self._select: dict[str, object] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        if tag == "form":
            self._form_depth += 1
        if self._form_depth != 1:
            return
        if tag == "input":
            name = attributes.get("name")
            if not isinstance(name, str):
                return
            input_type = attributes.get("type", "text")
            if input_type in {"checkbox", "radio"} and "checked" not in attributes:
                return
            self.controls.append((name, attributes.get("value") or ""))
        elif tag == "select" and isinstance(attributes.get("name"), str):
            self._select = {
                "name": attributes["name"],
                "first": None,
                "selected": None,
            }
        elif tag == "option" and self._select is not None:
            value = attributes.get("value") or ""
            if self._select["first"] is None:
                self._select["first"] = value
            if "selected" in attributes:
                self._select["selected"] = value

    def handle_endtag(self, tag: str) -> None:
        if tag == "select" and self._select is not None:
            value = self._select["selected"] or self._select["first"] or ""
            self.controls.append((str(self._select["name"]), str(value)))
            self._select = None
        elif tag == "form":
            self._form_depth -= 1


def parsed_form(text: str) -> list[tuple[str, str]]:
    parser = RenderedFormParser()
    parser.feed(text)
    return parser.controls


def encode_form(controls: list[tuple[str, str]]) -> str:
    """Serialize successful controls exactly like a browser form submission."""
    return urlencode(controls)


class _ScopedDataSource(SQLAlchemyDataSource):
    """Narrow the public visibility selectable for target-scope proofs."""

    def __init__(
        self,
        *,
        model: type[object],
        session_factory: async_sessionmaker[AsyncSession],
        field_policy: ResourceFieldPolicy,
        scope: Callable[[], Any],
    ) -> None:
        super().__init__(model=model, session_factory=session_factory, field_policy=field_policy)
        self._scope = scope

    def _base_statement(self) -> Any:
        return self._scope()


def _source(
    model: type[object],
    factory: async_sessionmaker[AsyncSession],
    *,
    scoped: Callable[[], Any] | None = None,
    search_fields: tuple[str, ...] = (),
) -> SQLAlchemyDataSource:
    policy = ResourceFieldPolicy(
        list_fields=("id",),
        detail_fields=("id",),
        search_fields=search_fields,
    )
    if scoped is not None:
        return _ScopedDataSource(
            model=model,
            session_factory=factory,
            field_policy=policy,
            scope=scoped,
        )
    return SQLAlchemyDataSource(
        model=model,
        session_factory=factory,
        field_policy=policy,
    )


async def _authorize(
    _request: object, operation: str, identity: RecordIdentity | None
) -> MutationAuthorization:
    return MutationAuthorization.for_requirement(
        admin_id=_ADMIN_ID,
        resource_id="orders",
        operation=operation,
        principal_id=_PRINCIPAL_ID,
        requirement=_REQ_ORDERS_UPDATE,
        target_identity=identity,
    )


def _reject_bad_sku(plan: Any) -> None:
    from rakit_core.errors import ErrorCode, RakitError

    values = getattr(plan, "values", None) or getattr(plan, "scalar_changes", {})
    if values.get("sku") == "bad-sku":
        raise RakitError(
            code=ErrorCode.VALIDATION_FAILED,
            message="SKU is not acceptable.",
            status_code=422,
        )


async def _allow(_request: object) -> bool:
    return True


async def _allow_editor(_request: object, _relationship_id: str, _parent: object) -> bool:
    return True


def _make_graph_authorization(
    relationships: tuple[CompiledRelationship, ...],
) -> Callable[[object, MutationAuthorization, RecordIdentity | None, tuple[object, ...]], Any]:
    entries = {entry.definition.relationship_id: entry for entry in relationships}

    async def _graph_authorization(
        _request: object,
        root: MutationAuthorization,
        parent: RecordIdentity | None,
        changes: tuple[object, ...],
    ) -> OperationAuthorizationSet:
        capabilities = []
        for change in cast(tuple[Any, ...], changes):
            capabilities.append(
                MutationAuthorization.for_requirement(
                    admin_id=_ADMIN_ID,
                    resource_id="orders",
                    operation=change.operation_id,
                    principal_id=_PRINCIPAL_ID,
                    requirement=change.authorization_requirement,
                    target_identity=None if parent is None else parent,
                )
            )
            entry = entries[change.relationship_id]
            target_resource_id = _target_resource_id(
                entry.definition.relationship_id,
                association=entry.definition.kind is RelationshipKind.ASSOCIATION_OBJECT,
            )
            for step in change.steps:
                if isinstance(step, DeleteRelated):
                    permission = entry.target_delete_permission
                    if permission is None:
                        continue
                    capabilities.append(
                        MutationAuthorization.for_requirement(
                            admin_id=_ADMIN_ID,
                            resource_id=target_resource_id,
                            operation=f"{change.operation_id}:target-delete",
                            principal_id=_PRINCIPAL_ID,
                            requirement=permission,
                            target_identity=step.identity,
                        )
                    )
                elif isinstance(step, CreateRelated):
                    permission = entry.target_create_permission
                    if permission is None:
                        continue
                    capabilities.append(
                        MutationAuthorization.for_requirement(
                            admin_id=_ADMIN_ID,
                            resource_id=target_resource_id,
                            operation=f"{change.operation_id}:target-create",
                            principal_id=_PRINCIPAL_ID,
                            requirement=permission,
                        )
                    )
                elif isinstance(step, UpdateRelated):
                    permission = entry.target_update_permission
                    if permission is None:
                        continue
                    capabilities.append(
                        MutationAuthorization.for_requirement(
                            admin_id=_ADMIN_ID,
                            resource_id=target_resource_id,
                            operation=f"{change.operation_id}:target-update",
                            principal_id=_PRINCIPAL_ID,
                            requirement=permission,
                            target_identity=step.identity,
                        )
                    )
        return OperationAuthorizationSet(root=root, capabilities=tuple(capabilities))

    return _graph_authorization


class _PrincipalMiddleware:
    def __init__(self, app: Any) -> None:
        self.app = app

    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        if scope["type"] == "http":
            scope.setdefault("state", {})["principal"] = Principal(
                subject_id=_PRINCIPAL_ID, authenticated=True
            )
        await self.app(scope, receive, send)


def _target_resource_id(relationship_id: str, *, association: bool) -> str:
    if association:
        return "enrollments"
    return {
        "customer": "customers",
        "tags": "tags",
        "line_items": "line_items",
        "attachments": "attachments",
    }[relationship_id]


def _compiled(
    relationship_id: str,
    *,
    kind: RelationshipKind,
    cardinality: RelationshipCardinality,
    edit_mode: RelationshipEditMode,
    label: str,
    ordering: RelationshipOrderingDefinition | None = None,
    association: bool = False,
    child_delete: bool = False,
    record_label_field: str = "name",
) -> CompiledRelationship:
    definition = RelationshipDefinition(
        relationship_id=relationship_id,
        target_resource_id=_target_resource_id(relationship_id, association=association),
        association_target_resource_id="courses" if association else None,
        association_fields=("grade",) if association else (),
        label=label,
        kind=kind,
        cardinality=cardinality,
        nullable=True,
        ordered=ordering is not None,
        ordering=ordering,
        writable=True,
        edit_mode=edit_mode,
        record_label_field=record_label_field,
        destructive_policy=RelationshipDestructivePolicy(allow_child_delete=child_delete),
    )
    return CompiledRelationship(
        source_resource_id="orders",
        definition=definition,
        mutation_permission=_REQ_ORDERS_UPDATE,
        target_delete_permission=_REQ_LINE_DELETE if child_delete else None,
        target_create_permission=_REQ_LINE_CREATE
        if edit_mode is RelationshipEditMode.INLINE and not association
        else None,
        target_update_permission=_REQ_LINE_UPDATE
        if edit_mode is RelationshipEditMode.INLINE and not association
        else None,
        ordering=ordering,
        route_path=f"/orders/{{identity}}/_relationships/{relationship_id}",
    )


@dataclass
class IntegrationApp:
    app: Any
    engine: AsyncEngine
    session_factory: async_sessionmaker[AsyncSession]
    codec: IdentityCodec
    parent_service: SQLAlchemyMutationService
    relationship_service: SQLAlchemyRelationshipMutationService
    store: MemoryIdempotencyStore
    db_path: str
    action_binding: Any | None = None


def build_app(factory: async_sessionmaker[AsyncSession]) -> IntegrationApp:
    token_service = TokenService.single_key(
        key_id="integration", value=SecretValue("x" * 32), admin_id=_ADMIN_ID
    )
    store = MemoryIdempotencyStore()
    codec = IdentityCodec()

    customer_source = _source(
        Customer,
        factory,
        scoped=lambda: select(Customer).where(Customer.enabled.is_(True)),
        search_fields=("name",),
    )
    tag_source = _source(Tag, factory)
    line_source = _source(LineItem, factory)
    course_source = _source(Course, factory)
    enrollment_source = _source(Enrollment, factory)

    parent_writer = SQLAlchemyMutationService(
        model=Order,
        session_factory=factory,
        form_schema=FormSchema(
            fields=(FieldDefinition(field_id="status", python_type=str, required=True),)
        ),
        writable_fields=("status",),
        identity_fields=("id",),
        resource_id="orders",
        token_service=token_service,
        concurrency_provider=AttributeVersionProvider("version"),
        graph_idempotency_store=store,
    )
    line_writer = SQLAlchemyMutationService(
        model=LineItem,
        session_factory=factory,
        form_schema=FormSchema(
            fields=(
                FieldDefinition(field_id="sku", python_type=str, required=True),
                FieldDefinition(field_id="quantity", python_type=int, required=True),
            )
        ),
        writable_fields=("sku", "quantity"),
        identity_fields=("id",),
        resource_id="line_items",
        token_service=token_service,
        concurrency_provider=AttributeVersionProvider("version"),
        delete_nonce_store=store,
        hooks=MutationHooks(
            business_validate=(_reject_bad_sku,),
            business_validate_update=(_reject_bad_sku,),
        ),
    )
    attachment_writer = SQLAlchemyMutationService(
        model=Attachment,
        session_factory=factory,
        form_schema=FormSchema(
            fields=(FieldDefinition(field_id="name", python_type=str, required=True),)
        ),
        writable_fields=("name",),
        identity_fields=("id",),
        resource_id="attachments",
        token_service=token_service,
        concurrency_provider=AttributeVersionProvider("version"),
    )

    line_ordering = RelationshipOrderingDefinition(position_field="position")
    relationships = (
        _compiled(
            "customer",
            kind=RelationshipKind.MANY_TO_ONE,
            cardinality=RelationshipCardinality.TO_ONE,
            edit_mode=RelationshipEditMode.LINK,
            label="Customer",
        ),
        _compiled(
            "tags",
            kind=RelationshipKind.MANY_TO_MANY,
            cardinality=RelationshipCardinality.TO_MANY,
            edit_mode=RelationshipEditMode.LINK,
            label="Tags",
        ),
        _compiled(
            "line_items",
            kind=RelationshipKind.ONE_TO_MANY,
            cardinality=RelationshipCardinality.TO_MANY,
            edit_mode=RelationshipEditMode.INLINE,
            label="Line items",
            ordering=line_ordering,
            child_delete=True,
            record_label_field="sku",
        ),
        _compiled(
            "attachments",
            kind=RelationshipKind.ONE_TO_MANY,
            cardinality=RelationshipCardinality.TO_MANY,
            edit_mode=RelationshipEditMode.INLINE,
            label="Attachments",
            record_label_field="name",
        ),
        _compiled(
            "enrollments",
            kind=RelationshipKind.ASSOCIATION_OBJECT,
            cardinality=RelationshipCardinality.TO_MANY,
            edit_mode=RelationshipEditMode.INLINE,
            label="Course enrolments",
            association=True,
        ),
    )
    relationship_writer = SQLAlchemyRelationshipMutationService(
        session_factory=factory,
        parent_data_source=_source(Order, factory),
        relationships=relationships,
        target_data_sources={
            "customers": customer_source,
            "tags": tag_source,
            "line_items": line_source,
            "courses": course_source,
            "enrollments": enrollment_source,
            "attachments": _source(Attachment, factory),
        },
        target_mutation_services={
            "line_items": line_writer,
            "attachments": attachment_writer,
        },
        token_service=token_service,
        concurrency_provider=AttributeVersionProvider("version"),
        idempotency_store=store,
    )
    parent_writer.bind_graph_relationship_service(relationship_writer, idempotency_store=store)

    def editor(
        relationship: CompiledRelationship,
        *,
        target_service: ResourceService,
        target_form_schema: FormSchema | None = None,
        association_form_schema: FormSchema | None = None,
        target_search_fields: tuple[str, ...] = (),
    ) -> RelationshipEditorBinding:
        return RelationshipEditorBinding(
            relationship=relationship,
            target_service=target_service,
            state_provider=relationship_writer,
            target_form_schema=target_form_schema,
            association_form_schema=association_form_schema,
            target_search_fields=target_search_fields,
            candidate_page_size=12,
            reorder_safe_maximum=10,
        )

    relationship_form = RelationshipFormBinding(
        editors=(
            editor(
                relationships[0],
                target_service=ResourceService(cast(Any, customer_source)),
                target_search_fields=("name",),
            ),
            editor(
                relationships[1],
                target_service=ResourceService(cast(Any, tag_source)),
                target_search_fields=("name",),
            ),
            editor(
                relationships[2],
                target_service=ResourceService(cast(Any, line_source)),
                target_form_schema=FormSchema(
                    fields=(
                        FieldDefinition(field_id="sku", python_type=str, required=True),
                        FieldDefinition(field_id="quantity", python_type=int, required=True),
                    )
                ),
            ),
            editor(
                relationships[3],
                target_service=ResourceService(cast(Any, _source(Attachment, factory))),
                target_form_schema=FormSchema(
                    fields=(FieldDefinition(field_id="name", python_type=str, required=True),)
                ),
            ),
            editor(
                relationships[4],
                target_service=ResourceService(cast(Any, course_source)),
                association_form_schema=FormSchema(
                    fields=(FieldDefinition(field_id="grade", python_type=str, required=True),)
                ),
            ),
        )
    )
    binding = WriteResourceBinding(
        path="/orders",
        label="Order",
        form_schema=FormSchema(
            fields=(FieldDefinition(field_id="status", python_type=str, required=True),),
            layout=FormLayout(
                children=(
                    FieldLayout("status"),
                    RelationshipPanel(layout_id="customer", relationship_id="customer"),
                    RelationshipPanel(layout_id="tags", relationship_id="tags"),
                    RelationshipPanel(layout_id="line_items", relationship_id="line_items"),
                    RelationshipPanel(layout_id="attachments", relationship_id="attachments"),
                    RelationshipPanel(layout_id="enrollments", relationship_id="enrollments"),
                )
            ),
        ),
        mutation_service=parent_writer,
        templates=build_templates(()),
        authorize=_allow,
        verify_csrf=_allow,
        verify_submission_token=_allow,
        issue_submission_token=lambda _request: uuid4().hex,
        mutation_authorizer=_authorize,
        graph_mutation_authorizer=_make_graph_authorization(relationships),
        relationship_editor_authorizer=_allow_editor,
        relationship_form=relationship_form,
        deadline_seconds=60,
    )

    def approve_availability(context: Any) -> ActionAvailabilityDecision:
        if cast(Order, context.record).status == "draft":
            return ActionAvailabilityDecision.available()
        return ActionAvailabilityDecision.disabled("Order is not pending approval")

    def approve_prepare(_context: ActionContext) -> dict[str, object]:
        return {"status": "approved"}

    async def approve_commit(plan: object, context: ActionContext) -> ActionSuccess[object]:
        await parent_writer.update(
            cast(RecordIdentity, context.identity),
            cast(dict[str, object], plan),
            concurrency_token=context.concurrency_token,
            authorization=context.authorization,
        )
        return ActionSuccess(message="Order approved")

    async def authorize_action(
        request: Request,
        compiled_action: CompiledActionDefinition,
        identity: RecordIdentity | None,
    ) -> OperationAuthorization | None:
        principal = request.scope.get("state", {}).get("principal")
        if principal is None or not principal.authenticated:
            return None
        return OperationAuthorization.for_requirement(
            admin_id=_ADMIN_ID,
            resource_id="orders",
            operation="update",
            principal_id=_PRINCIPAL_ID,
            requirement=compiled_action.permission,
            target_identity=identity,
        )

    action_binding = ActionBinding(
        routes=(
            (
                RouteDefinition(
                    route_name="resource:orders:action:approve",
                    methods=("GET", "POST"),
                    path="/orders/{identity}/_actions/approve",
                    owner_id="orders",
                ),
                CompiledActionDefinition(
                    definition=ActionDefinition(
                        action_id="approve",
                        label="Approve order",
                        scope=ActionScope.RECORD,
                        resource_id="orders",
                        permission=_REQ_ORDERS_UPDATE,
                        description="Approve this order for fulfilment.",
                        availability=approve_availability,
                        executor=_IntegrationAtomicPreparedMutationExecutor(
                            approve_prepare,
                            approve_commit,
                        ),
                        mutating=True,
                        transaction_policy=TransactionPolicy.AUTO,
                        requires_concurrency=True,
                    ),
                    permission=_REQ_ORDERS_UPDATE,
                ),
            ),
        ),
        templates=build_templates(()),
        codec=codec,
        verify_csrf=_allow,
        verify_submission_token=_allow,
        issue_submission_token=lambda _request: uuid4().hex,
        authorize_action=authorize_action,
        load_record=parent_writer.get,
        record_version=lambda record: cast(Order, record).version,
        concurrency=ConcurrencyTokenService(token_service),
        concurrency_resource_id="orders",
        token_service=token_service,
        idempotency_store=store,
        deadline_seconds=60,
        unit_of_work_factory=lambda: SQLAlchemyOperationUnitOfWorkFactory(factory),
    )
    app = _PrincipalMiddleware(
        Starlette(
            routes=[
                *build_write_routes(binding),
                *build_relationship_routes(binding, relationship_form),
                *build_action_routes(action_binding),
                Mount("/_system/static", app=static_files()),
            ]
        )
    )
    return IntegrationApp(
        app=app,
        engine=cast(Any, None),
        session_factory=factory,
        codec=codec,
        parent_service=parent_writer,
        relationship_service=relationship_writer,
        store=store,
        db_path="",
        action_binding=action_binding,
    )


async def seed_graph(
    factory: async_sessionmaker[AsyncSession],
) -> dict[str, object]:
    async with factory() as session:
        customers = (
            Customer(id=1, name="Ada", enabled=True),
            Customer(id=2, name="Grace", enabled=False),
            Customer(id=3, name="Hedy", enabled=True),
        )
        tags = tuple(Tag(id=index, name=f"Tag {index:02d}") for index in range(1, 5))
        courses = (Course(id=1, name="Math"), Course(id=2, name="Physics"))
        session.add_all([*customers, *tags, *courses])
        order = Order(id=10, status="draft", customer=customers[0])
        order.tags = [tags[0]]
        order.line_items = [
            LineItem(id=21, sku="SKU-021", quantity=1, position=1),
            LineItem(id=22, sku="SKU-022", quantity=2, position=2),
            LineItem(id=23, sku="SKU-023", quantity=3, position=3),
        ]
        order.enrollments = [
            Enrollment(id=31, course=courses[0], grade="B"),
            Enrollment(id=32, course=courses[1], grade="A"),
        ]
        order.attachments = [Attachment(id=41, name="Note")]
        session.add(order)
        await session.commit()
    return {
        "order": RecordIdentity(values={"id": 10}),
        "customer_ada": RecordIdentity(values={"id": 1}),
        "customer_grace_off_scope": RecordIdentity(values={"id": 2}),
        "customer_hedy": RecordIdentity(values={"id": 3}),
        "tag_one": RecordIdentity(values={"id": 1}),
        "tag_two": RecordIdentity(values={"id": 2}),
        "line_21": RecordIdentity(values={"id": 21}),
        "line_22": RecordIdentity(values={"id": 22}),
        "line_23": RecordIdentity(values={"id": 23}),
        "course_one": RecordIdentity(values={"id": 1}),
        "course_two": RecordIdentity(values={"id": 2}),
        "enrollment_31": RecordIdentity(values={"id": 31}),
        "attachment_41": RecordIdentity(values={"id": 41}),
    }


@pytest.fixture
async def integration(
    tmp_path: Any,
) -> AsyncIterator[tuple[IntegrationApp, dict[str, object]]]:
    database_path = tmp_path / "rakit-phase3b.sqlite"
    engine = create_async_engine(f"sqlite+aiosqlite:///{database_path.as_posix()}")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    app = build_app(factory)
    app.engine = engine
    app.db_path = database_path.as_posix()
    identities = await seed_graph(factory)
    try:
        yield app, identities
    finally:
        await engine.dispose()


@pytest.fixture
def parent(integration: tuple[IntegrationApp, dict[str, object]]) -> str:
    app, identities = integration
    return app.codec.encode(cast(RecordIdentity, identities["order"]))


@pytest.fixture
def codec(integration: tuple[IntegrationApp, dict[str, object]]) -> IdentityCodec:
    app, _ = integration
    return app.codec


class StatementRecorder:
    """Capture emitted SQL statements on the real engine for query proofs."""

    def __init__(self, engine: AsyncEngine) -> None:
        self.statements: list[str] = []
        self._listener = self._before_cursor_execute
        event.listen(engine.sync_engine, "before_cursor_execute", self._listener)

    def _before_cursor_execute(
        self,
        _conn: object,
        _cursor: object,
        statement: str,
        _parameters: object,
        _context: object,
        _executemany: bool,
    ) -> None:
        self.statements.append(statement)

    def close(self, engine: AsyncEngine) -> None:
        event.remove(engine.sync_engine, "before_cursor_execute", self._listener)


class CommitRecorder:
    """Count real database commits on the engine for root-transaction proofs."""

    def __init__(self, engine: AsyncEngine) -> None:
        self.commits = 0
        self._listener = self._on_commit
        event.listen(engine.sync_engine, "commit", self._listener)

    def _on_commit(self, _conn: object) -> None:
        self.commits += 1

    def close(self, engine: AsyncEngine) -> None:
        event.remove(engine.sync_engine, "commit", self._listener)


async def fetch_orders(factory: async_sessionmaker[AsyncSession]) -> list[tuple[str, int]]:
    async with factory() as session:
        rows = (await session.scalars(select(Order))).all()
        return [(row.status, row.version) for row in rows]


async def fetch_line_items(
    factory: async_sessionmaker[AsyncSession],
) -> list[tuple[int, str, int, int, int]]:
    async with factory() as session:
        rows = (
            await session.execute(
                select(LineItem).order_by(LineItem.position.asc(), LineItem.id.asc())
            )
        ).scalars()
        return [(item.id, item.sku, item.quantity, item.position, item.version) for item in rows]


async def fetch_order_relationship(
    factory: async_sessionmaker[AsyncSession],
) -> tuple[tuple[int | None, ...], tuple[int, ...], tuple[tuple[int, str], ...]]:
    from sqlalchemy.orm import selectinload

    async with factory() as session:
        order = (
            await session.execute(
                select(Order)
                .where(Order.id == 10)
                .options(
                    selectinload(Order.tags),
                    selectinload(Order.enrollments),
                    selectinload(Order.customer),
                )
            )
        ).scalar_one()
        customer_id = order.customer_id
        tag_ids = tuple(sorted(tag.id for tag in order.tags))
        enrollments = tuple(
            sorted((enrollment.course_id, enrollment.grade) for enrollment in order.enrollments)
        )
        return (customer_id,), tag_ids, enrollments


def client_for(app: IntegrationApp) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app.app), base_url="http://test")


def replace_control(
    controls: list[tuple[str, str]], name: str, value: str
) -> list[tuple[str, str]]:
    return [
        (control_name, value if control_name == name else control_value)
        for control_name, control_value in controls
    ]


def append_controls(
    controls: list[tuple[str, str]], *additional: tuple[str, str]
) -> list[tuple[str, str]]:
    return [*controls, *additional]
