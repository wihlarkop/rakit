import pytest
from rakit import Admin, DataSourceCapabilities, ModelAdmin, ResourceWriteDefinition, SecretValue
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
from rakit_core.compiler import ApplicationBuilder
from rakit_core.errors import RakitError
from rakit_core.fields import FieldDefinition
from rakit_core.generated_runtime import (
    ResourceAdapterRuntime,
    ResourceWriteServiceContext,
    ResourceWriteServiceProvider,
)


class _Model:
    pass


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


SCHEMA = FormSchema(fields=(FieldDefinition(field_id="name", python_type=str, required=True),))
WRITE = ResourceWriteDefinition(
    form_schema=SCHEMA,
    writable_fields=("name",),
    success_message="Saved declaratively.",
    htmx_refresh_targets=("rakit:refresh",),
)


class _MutableResource(ModelAdmin):
    resource_id = "things"
    path = "/things"
    label = "Things"
    singular_label = "Thing"
    model = _Model
    list_fields = ("id", "name")
    detail_fields = ("id", "name")
    write = WRITE


class _ReadOnlyResource(ModelAdmin):
    resource_id = "readonly"
    path = "/readonly"
    label = "Read only"
    singular_label = "Read only thing"
    model = _Model
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


class _FullMutationService:
    def __init__(self) -> None:
        self.delete_nonce_store: object | None = None

    def bind_delete_nonce_store(self, store: object) -> None:
        self.delete_nonce_store = store

    async def create(self, submitted: object, *, authorization: object | None = None) -> object:
        del authorization
        return submitted

    async def get(self, identity: object) -> object:
        return identity

    def issue_update_token(self, record: object) -> str:
        del record
        return "update-token"

    async def update(self, *args: object, **kwargs: object) -> object:
        del args, kwargs
        return object()

    def issue_delete_token(self, record: object) -> str:
        del record
        return "delete-token"

    async def delete(self, *args: object, **kwargs: object) -> object:
        del args, kwargs
        return object()


class _Provider:
    def __init__(self, service: object | None = None) -> None:
        self.context: ResourceWriteServiceContext | None = None
        self.service = service if service is not None else _FullMutationService()

    def build(self, context: ResourceWriteServiceContext) -> object:
        self.context = context
        return self.service


class _AdapterPlugin:
    plugin_id = "c1-test-adapter"

    def __init__(self, provider: ResourceWriteServiceProvider | None) -> None:
        self.provider = provider

    def configure(self, builder: ApplicationBuilder) -> None:
        provider = self.provider

        def claim(model: type[object], _field_policy: object) -> ResourceAdapterRuntime | None:
            if model is not _Model:
                return None
            return ResourceAdapterRuntime(
                data_source=_DataSource(),
                write_service_provider=provider,
            )

        builder.register_adapter(self.plugin_id, claim)


def _admin() -> Admin:
    return Admin(
        admin_id="backoffice",
        title="C1 declarative writes",
        debug=True,
        secret_key=SecretValue("x" * 32),
        auth_backend=_AuthBackend(),
        session_store=_SessionStore(),
        operation_idempotency_store=_IdempotencyStore(),
    )


def test_register_materializes_explicit_write_policy_through_adapter() -> None:
    provider = _Provider()
    admin = _admin()
    admin.install(_AdapterPlugin(provider))

    admin.register(_MutableResource)

    context = provider.context
    assert context is not None
    assert context.admin_id == "backoffice"
    assert context.resource_id == "things"
    assert context.definition is WRITE
    binding = admin._write_resource_bindings["things"]
    assert binding.form_schema is SCHEMA
    assert binding.success_message == "Saved declaratively."
    assert binding.htmx_refresh_targets == ("rakit:refresh",)
    assert isinstance(provider.service, _FullMutationService)
    assert provider.service.delete_nonce_store is binding.idempotency_store


def test_register_keeps_resource_read_only_without_explicit_write_policy() -> None:
    provider = _Provider()
    admin = _admin()
    admin.install(_AdapterPlugin(provider))

    admin.register(_ReadOnlyResource)

    assert "readonly" not in admin._write_resource_bindings
    assert provider.context is None


def test_register_fails_closed_when_adapter_has_no_write_provider() -> None:
    admin = _admin()
    admin.install(_AdapterPlugin(None))

    with pytest.raises(RakitError, match="cannot provide declared resource writes"):
        admin.register(_MutableResource)

    assert "things" not in admin._write_resource_bindings


def test_register_fails_closed_on_incomplete_write_service() -> None:
    provider = _Provider(service=object())
    admin = _admin()
    admin.install(_AdapterPlugin(provider))

    with pytest.raises(RakitError, match="invalid resource write service"):
        admin.register(_MutableResource)

    assert "things" not in admin._write_resource_bindings
