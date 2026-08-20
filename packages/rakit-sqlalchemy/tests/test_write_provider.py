from rakit_core.admin_types import ResourceWriteDefinition
from rakit_core.config import SecretValue
from rakit_core.crypto import TokenService
from rakit_core.definitions import ResourceFieldPolicy
from rakit_core.fields import FieldDefinition
from rakit_core.forms import FormSchema
from rakit_core.generated_runtime import ResourceAdapterRuntime, ResourceWriteServiceContext
from rakit_sqlalchemy.mutations import SQLAlchemyMutationService
from rakit_sqlalchemy.plugin import SQLAlchemyPlugin
from rakit_sqlalchemy.write_provider import SQLAlchemyWriteServiceProvider
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Thing(Base):
    __tablename__ = "c1_write_provider_things"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str]
    version: Mapped[int] = mapped_column(default=1)


def _session_factory() -> async_sessionmaker[AsyncSession]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    return async_sessionmaker(engine, expire_on_commit=False)


def _definition() -> ResourceWriteDefinition:
    return ResourceWriteDefinition(
        form_schema=FormSchema(
            fields=(FieldDefinition(field_id="name", python_type=str, required=True),)
        ),
        writable_fields=("name",),
        version_field="version",
    )


def _context() -> ResourceWriteServiceContext:
    return ResourceWriteServiceContext(
        admin_id="backoffice",
        resource_id="things",
        definition=_definition(),
        token_service=TokenService.single_key(
            key_id="primary",
            value=SecretValue("x" * 32),
            admin_id="backoffice",
        ),
    )


def test_sqlalchemy_write_provider_derives_identity_and_canonical_permissions() -> None:
    provider = SQLAlchemyWriteServiceProvider(
        model=Thing,
        session_factory=_session_factory(),
    )

    service = provider.build(_context())

    assert isinstance(service, SQLAlchemyMutationService)
    assert service._identity_fields == ("id",)
    assert service._writable_fields == frozenset({"name"})
    assert service._version_field == "version"
    assert service._resource_id == "things"
    assert service._delete_permission == "backoffice.resources.things.delete"
    assert service._force_overwrite_permission == "backoffice.resources.things.force_overwrite"


def test_sqlalchemy_plugin_claim_exposes_write_provider_for_mapped_model() -> None:
    plugin = SQLAlchemyPlugin(session_factory=_session_factory())
    from rakit_core.compiler import ApplicationBuilder

    builder = ApplicationBuilder()
    plugin.configure(builder)
    runtime = builder._adapters["sqlalchemy"](
        Thing,
        ResourceFieldPolicy(list_fields=("id", "name"), detail_fields=("id", "name")),
    )

    assert isinstance(runtime, ResourceAdapterRuntime)
    assert isinstance(runtime.write_service_provider, SQLAlchemyWriteServiceProvider)
