from datetime import UTC, datetime, timedelta

import httpx
import pytest
from rakit import (
    Admin,
    ApiExposure,
    PageSizePolicy,
    ResourceAdmin,
    ResourceApiDefinition,
    ResourcePaginationPolicy,
    SecretValue,
)
from rakit_core.auth import Principal, SessionRecord
from rakit_core.datasource import DataSourceCapabilities
from rakit_core.generated_api import ApiFilterDefinition
from rakit_core.identity import IdentityCodec, RecordIdentity
from rakit_core.query import FilterOperator, PageResult, ResourceQuery
from rakit_web.security.cookies import SESSION_COOKIE_NAME
from starlette.applications import Starlette
from starlette.routing import Mount


class UsersDataSource:
    capabilities = DataSourceCapabilities(read=True)
    fields = ("id", "email", "status", "secret")
    identity_fields = ("id",)

    def __init__(self) -> None:
        self.last_query: ResourceQuery | None = None
        self.records = {
            1: {"id": 1, "email": "one@example.com", "status": "active", "secret": "one"},
            2: {"id": 2, "email": "two@example.com", "status": "pending", "secret": "two"},
        }

    async def list(self, query):
        self.last_query = query
        return PageResult(
            items=tuple(self.records.values()),
            page=query.pagination.page,
            per_page=query.pagination.per_page,
            has_previous=query.pagination.page > 1,
            has_next=False,
            total_count=len(self.records),
        )

    async def count(self, query):
        return len(self.records)

    async def detail(self, identity):
        return self.records.get(identity.values.get("id"))


DATA_SOURCE = UsersDataSource()


class UsersAdmin(ResourceAdmin):
    resource_id = "users"
    path = "/users"
    label = "Users"
    singular_label = "User"
    list_fields = ("id", "email", "status")
    detail_fields = ("id", "email", "status")
    filter_fields = ("status",)
    search_fields = ("email",)
    sort_fields = ("email",)
    pagination = ResourcePaginationPolicy(
        size=PageSizePolicy(default=25, allowed=(10, 25, 50, 100))
    )
    data_source = DATA_SOURCE
    api = ResourceApiDefinition(
        exposure=ApiExposure.READ_ONLY,
        read_fields=("id", "email", "status"),
        filters=(
            ApiFilterDefinition(
                name="status",
                field="status",
                operators=(FilterOperator.EQ, FilterOperator.IN),
            ),
        ),
    )


def _admin(**kwargs) -> Admin:
    admin = Admin(
        admin_id="ops",
        title="Generated REST",
        debug=True,
        secret_key=SecretValue("x" * 32),
        **kwargs,
    )
    admin.register(UsersAdmin)
    return admin


@pytest.mark.anyio
async def test_generated_rest_list_and_detail_are_json_and_read_field_bounded() -> None:
    app = _admin().asgi()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://localhost") as client:
        response = await client.get(
            "/api/users",
            params={"page": "2", "per_page": "10", "filter[status]": "active"},
        )
        identity = IdentityCodec().encode(RecordIdentity(values={"id": 1}))
        detail = await client.get(f"/api/users/{identity}")

    assert response.status_code == 200
    assert response.json() == {
        "data": [
            {"id": 1, "email": "one@example.com", "status": "active"},
            {"id": 2, "email": "two@example.com", "status": "pending"},
        ],
        "meta": {
            "page": 2,
            "per_page": 10,
            "has_previous": True,
            "has_next": False,
            "total": 2,
        },
    }
    assert DATA_SOURCE.last_query is not None
    assert DATA_SOURCE.last_query.filters[0].field == "status"
    assert detail.status_code == 200
    assert detail.json() == {"data": {"id": 1, "email": "one@example.com", "status": "active"}}


@pytest.mark.anyio
async def test_generated_rest_invalid_query_uses_json_error_envelope() -> None:
    app = _admin().asgi()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://localhost") as client:
        response = await client.get("/api/users?sort=secret")

    assert response.status_code == 400
    payload = response.json()
    assert payload["error"]["code"] == "validation.failed"
    assert payload["error"]["details"]["reason"] == "generated_api_query_not_allowed"
    assert isinstance(payload["request_id"], str) and payload["request_id"]
    assert response.headers["cache-control"] == "no-store"


class ExplodingDataSource:
    capabilities = DataSourceCapabilities(read=True)
    fields = ("id", "name")
    identity_fields = ("id",)

    async def list(self, query):
        raise RuntimeError("sensitive backend detail")

    async def count(self, query):
        return 0

    async def detail(self, identity):
        raise RuntimeError("sensitive backend detail")


class ExplodingAdmin(ResourceAdmin):
    resource_id = "exploding"
    path = "/exploding"
    label = "Exploding"
    singular_label = "Exploding"
    list_fields = ("id", "name")
    detail_fields = ("id", "name")
    data_source = ExplodingDataSource()
    api = ResourceApiDefinition(
        exposure=ApiExposure.READ_ONLY,
        read_fields=("id", "name"),
    )


@pytest.mark.anyio
async def test_generated_rest_unexpected_failure_is_safe_json_even_in_debug_mode() -> None:
    admin = Admin(title="REST failure", debug=True)
    admin.register(ExplodingAdmin)
    transport = httpx.ASGITransport(app=admin.asgi(), raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://localhost") as client:
        response = await client.get("/api/exploding")

    assert response.status_code == 500
    assert response.headers["content-type"].startswith("application/json")
    assert response.headers["cache-control"] == "no-store"
    payload = response.json()
    assert payload["error"] == {
        "code": "internal.error",
        "message": "Internal server error.",
    }
    assert payload["request_id"]
    assert "sensitive backend detail" not in response.text


@pytest.mark.anyio
async def test_generated_rest_routes_work_when_admin_is_mounted() -> None:
    mounted = Starlette(routes=[Mount("/admin", app=_admin().asgi())])
    transport = httpx.ASGITransport(app=mounted)
    async with httpx.AsyncClient(transport=transport, base_url="http://localhost") as client:
        response = await client.get("/admin/api/users")

    assert response.status_code == 200
    assert response.json()["data"][0]["email"] == "one@example.com"


class AuthBackend:
    def __init__(self, principal: Principal) -> None:
        self.principal = principal

    async def authenticate(self, identifier: str, password: str):
        return None

    async def resolve_principal(self, subject_id: str):
        return self.principal if subject_id == self.principal.subject_id else None


class SessionStore:
    production_safe = False

    def __init__(self, principal: Principal) -> None:
        self.principal = principal

    async def create(self, principal: Principal):
        raise NotImplementedError

    async def resolve(self, raw_token: str):
        if raw_token != "valid" or self.principal.subject_id is None:
            return None
        now = datetime.now(UTC)
        return SessionRecord(
            session_id="session-1",
            subject_id=self.principal.subject_id,
            created_at=now,
            last_seen_at=now,
            idle_expires_at=now + timedelta(hours=1),
            absolute_expires_at=now + timedelta(days=1),
        )

    async def rotate(self, session_id: str):
        raise NotImplementedError

    async def revoke(self, session_id: str):
        return None


def _auth_admin(principal: Principal) -> Admin:
    return _admin(
        auth_backend=AuthBackend(principal),
        session_store=SessionStore(principal),
    )


@pytest.mark.anyio
async def test_generated_rest_auth_failures_are_json_not_browser_redirects() -> None:
    principal = Principal(subject_id="user-1", authenticated=True, permissions=frozenset())
    app = _auth_admin(principal).asgi()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://localhost") as client:
        anonymous = await client.get("/api/users")
        client.cookies.set(SESSION_COOKIE_NAME, "valid")
        forbidden = await client.get("/api/users")

    assert anonymous.status_code == 401
    assert anonymous.json()["error"]["code"] == "auth.unauthenticated"
    assert forbidden.status_code == 403
    assert forbidden.json()["error"]["code"] == "auth.forbidden"


@pytest.mark.anyio
async def test_generated_rest_authenticated_read_uses_resource_read_permission() -> None:
    principal = Principal(
        subject_id="user-1",
        authenticated=True,
        permissions=frozenset({"ops.resources.users.read"}),
    )
    app = _auth_admin(principal).asgi()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://localhost") as client:
        client.cookies.set(SESSION_COOKIE_NAME, "valid")
        response = await client.get("/api/users")

    assert response.status_code == 200
