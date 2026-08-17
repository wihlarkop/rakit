import httpx
import pytest


@pytest.mark.anyio
async def test_ui_showcase_exposes_dashboard_ui_lab_and_resources() -> None:
    from examples.ui_showcase.main import admin

    app = admin.asgi()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://localhost",
    ) as client:
        dashboard = await client.get("/")
        ui_lab = await client.get("/ui-lab")
        orders = await client.get("/orders")

    assert dashboard.status_code == 200
    assert ui_lab.status_code == 200
    assert orders.status_code == 200
    assert "Rakit Commerce" in dashboard.text
    assert "UI Lab" in ui_lab.text
