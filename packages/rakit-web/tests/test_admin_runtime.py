import httpx
import pytest
from rakit import Admin, SecretValue


@pytest.mark.anyio
async def test_admin_root_responds() -> None:
    admin = Admin(
        admin_id="operations",
        title="Operations",
        debug=False,
        secret_key=SecretValue("x" * 32),
    )
    app = admin.asgi()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        response = await client.get("/")
    assert response.status_code == 200
    assert response.text == "Operations"
