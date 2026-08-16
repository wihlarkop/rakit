import httpx
import pytest
from rakit import Admin, ApiExposure, ResourceAdmin, ResourceApiDefinition
from rakit_core.datasource import DataSourceCapabilities
from rakit_core.query import PageResult


class DataSource:
    capabilities = DataSourceCapabilities(read=True)
    fields = ("id", "name")
    identity_fields = ("id",)

    async def list(self, query):
        return PageResult((), 1, 25, False, False, 0)

    async def count(self, query):
        return 0

    async def detail(self, identity):
        return None


class ItemAdmin(ResourceAdmin):
    resource_id = "items"
    path = "/items"
    label = "Items"
    singular_label = "Item"
    list_fields = ("id", "name")
    detail_fields = ("id", "name")
    data_source = DataSource()
    api = ResourceApiDefinition(
        exposure=ApiExposure.READ_ONLY,
        read_fields=("id", "name"),
    )


def _app():
    admin = Admin(title="REST errors", debug=True)
    admin.register(ItemAdmin)
    return admin.asgi()


@pytest.mark.anyio
async def test_unknown_generated_api_path_returns_json_404() -> None:
    transport = httpx.ASGITransport(app=_app())
    async with httpx.AsyncClient(transport=transport, base_url="http://localhost") as client:
        response = await client.get("/api/unknown")

    assert response.status_code == 404
    assert response.headers["content-type"].startswith("application/json")
    assert response.headers["cache-control"] == "no-store"
    assert response.json()["error"] == {
        "code": "http.not_found",
        "message": "Not Found",
    }
    assert response.json()["request_id"]


@pytest.mark.anyio
async def test_unsupported_generated_api_method_returns_json_405() -> None:
    transport = httpx.ASGITransport(app=_app())
    async with httpx.AsyncClient(transport=transport, base_url="http://localhost") as client:
        response = await client.post("/api/items", json={})

    assert response.status_code == 405
    assert response.headers["content-type"].startswith("application/json")
    assert {item.strip() for item in response.headers["allow"].split(",")} == {"GET", "HEAD"}
    assert response.json()["error"] == {
        "code": "http.method_not_allowed",
        "message": "Method Not Allowed",
    }
    assert response.json()["request_id"]
