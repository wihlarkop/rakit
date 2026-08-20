from datetime import UTC, datetime, timedelta

import pytest
from rakit import Admin, DataSourceCapabilities, ResourceAdmin, SecretValue
from rakit.core import (
    FormSchema,
    IdempotencyReservation,
    IdempotencyStatus,
    OperationReceipt,
    PagePagination,
    PageResult,
    Principal,
    RecordIdentity,
    ResourceQuery,
    SessionRecord,
)
from rakit_core.fields import FieldDefinition


class _DataSource:
    capabilities = DataSourceCapabilities(read=True)
    fields = ("id", "name")
    identity_fields = ("id",)

    async def list(self, query: ResourceQuery) -> PageResult[dict[str, object]]:
        pagination = query.pagination
        assert isinstance(pagination, PagePagination)
        return PageResult(
            items=(),
            page=pagination.page,
            per_page=pagination.per_page,
            has_previous=False,
            has_next=False,
            total_count=0,
        )

    async def count(self, query: ResourceQuery) -> int:
        del query
        return 0

    async def detail(self, identity: RecordIdentity) -> None:
        del identity
        return None


class _Resource(ResourceAdmin):
    resource_id = "things"
    path = "/things"
    label = "Things"
    singular_label = "Thing"
    data_source = _DataSource()
    list_fields = ("id", "name")
    detail_fields = ("id", "name")


class _AuthBackend:
    async def authenticate(self, identifier: str, password: str) -> Principal | None:
        del identifier, password
        return None

    async def resolve_principal(self, subject_id: str) -> Principal | None:
        del subject_id
        return None


class _SessionStore:
    production_safe = False

    async def create(self, principal: Principal) -> tuple[str, SessionRecord]:
        del principal
        raise NotImplementedError

    async def resolve(self, raw_token: str) -> SessionRecord | None:
        del raw_token
        return None

    async def rotate(self, session_id: str) -> tuple[str, SessionRecord]:
        del session_id
        raise NotImplementedError

    async def revoke(self, session_id: str) -> None:
        del session_id


class _IdempotencyStore:
    production_safe = False

    async def begin(self, token_hash: str, *, fingerprint: str) -> IdempotencyReservation:
        del token_hash, fingerprint
        return IdempotencyReservation(1, IdempotencyStatus.IN_PROGRESS)

    async def complete(
        self, reservation: IdempotencyReservation, receipt: OperationReceipt
    ) -> None:
        del reservation, receipt

    async def release(self, reservation: IdempotencyReservation) -> None:
        del reservation

    async def fail_final(self, reservation: IdempotencyReservation) -> None:
        del reservation


class _MutationService:
    async def create(self, submitted: object, *, authorization: object | None = None) -> object:
        del authorization
        return submitted


def _admin(store: _IdempotencyStore | None = None) -> Admin:
    return Admin(
        title="Write composition",
        debug=True,
        secret_key=SecretValue("x" * 32),
        auth_backend=_AuthBackend(),
        session_store=_SessionStore(),
        operation_idempotency_store=store,
    )


def test_register_write_builds_low_level_binding_from_public_inputs() -> None:
    store = _IdempotencyStore()
    admin = _admin(store)
    admin.register(_Resource)
    schema = FormSchema(
        fields=(FieldDefinition(field_id="name", python_type=str, required=True),)
    )

    admin.register_write(
        "things",
        form_schema=schema,
        mutation_service=_MutationService(),
        success_message="Saved.",
    )

    binding = admin._write_resource_bindings["things"]
    assert binding.path == "/things"
    assert binding.label == "Thing"
    assert binding.form_schema is schema
    assert binding.idempotency_store is store
    assert binding.success_message == "Saved."


def test_register_write_rejects_unknown_resource() -> None:
    admin = _admin(_IdempotencyStore())
    schema = FormSchema(
        fields=(FieldDefinition(field_id="name", python_type=str, required=True),)
    )

    with pytest.raises(Exception, match="Invalid resource write policy declaration"):
        admin.register_write(
            "missing",
            form_schema=schema,
            mutation_service=_MutationService(),
        )


def test_register_write_requires_an_idempotency_store() -> None:
    admin = _admin()
    admin.register(_Resource)
    schema = FormSchema(
        fields=(FieldDefinition(field_id="name", python_type=str, required=True),)
    )

    with pytest.raises(Exception, match="Write resources require an idempotency store"):
        admin.register_write(
            "things",
            form_schema=schema,
            mutation_service=_MutationService(),
        )
