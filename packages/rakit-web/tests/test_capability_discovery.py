from collections.abc import Mapping

import pytest
from rakit_core.auth import AuthBackend, Principal, SessionRecord, SessionStore
from rakit_core.capabilities import CapabilityProvider, CapabilitySet
from rakit_core.errors import RakitError
from rakit_core.integrations import IntegrationDescriptor
from rakit_core.schema import SchemaAdapter, SchemaField
from rakit_web.admin import Admin


class CustomSchemaAdapter:
    provider = CapabilityProvider(
        "schema.custom",
        CapabilitySet.of("schema.input-validation"),
    )

    def fields(self, schema: type[object]) -> tuple[SchemaField, ...]:
        return ()

    def field_names(self, schema: type[object]) -> tuple[str, ...]:
        return ()

    def validate_input(self, schema: type[object], values: Mapping[str, object]) -> object:
        return dict(values)

    def serialize_output(self, schema: type[object], value: object) -> object:
        return value


class CustomAuthBackend:
    async def authenticate(self, identifier: str, password: str) -> Principal | None:
        return None

    async def resolve_principal(self, subject_id: str) -> Principal | None:
        return None


class CustomSessionStore:
    @property
    def production_safe(self) -> bool:
        return True

    async def create(self, principal: Principal) -> tuple[str, SessionRecord]:
        raise NotImplementedError

    async def resolve(self, raw_token: str) -> SessionRecord | None:
        return None

    async def rotate(self, session_id: str) -> tuple[str, SessionRecord]:
        raise NotImplementedError

    async def revoke(self, session_id: str) -> None:
        return None


class MetadataAuthBackend(CustomAuthBackend):
    rakit_integration = IntegrationDescriptor("auth.backend", "authentication", "Backend")


class MetadataSessionStore(CustomSessionStore):
    rakit_integration = IntegrationDescriptor("auth.store", "authentication", "Store")


def test_default_admin_records_only_configured_web_and_schema_integrations() -> None:
    admin = Admin(title="Capability discovery", debug=True)

    assert tuple(item.integration_id for item in admin.builder.configured_integrations) == (
        "schema.pydantic",
        "web.starlette",
    )


def test_custom_schema_is_reported_as_custom_unknown_without_inventing_identity() -> None:
    adapter: SchemaAdapter = CustomSchemaAdapter()

    admin = Admin(title="Custom schema", debug=True, schema_adapter=adapter)

    configured = admin.builder.configured_integrations
    assert tuple(item.integration_id for item in configured) == (
        "web.starlette",
        None,
    )
    assert configured[1].category == "schema"
    assert configured[1].display_name == "Custom / unknown schema"
    assert tuple(provider.provider_id for provider in admin.builder.capability_providers) == (
        "web.starlette",
        "schema.custom",
    )


def test_custom_auth_is_reported_as_custom_unknown_without_inventing_identity() -> None:
    backend: AuthBackend = CustomAuthBackend()
    store: SessionStore = CustomSessionStore()

    admin = Admin(
        title="Custom auth",
        debug=True,
        auth_backend=backend,
        session_store=store,
    )

    configured = admin.builder.configured_integrations
    assert tuple(item.integration_id for item in configured) == (
        "web.starlette",
        "schema.pydantic",
        None,
    )
    assert configured[2].category == "authentication"
    assert configured[2].display_name == "Custom / unknown authentication"


def test_conflicting_auth_integration_metadata_fails_closed() -> None:
    backend: AuthBackend = MetadataAuthBackend()
    store: SessionStore = MetadataSessionStore()

    with pytest.raises(RakitError) as captured:
        Admin(
            title="Conflicting auth",
            debug=True,
            auth_backend=backend,
            session_store=store,
        )

    assert captured.value.details == {"reason": "auth_integration_metadata_conflict"}
