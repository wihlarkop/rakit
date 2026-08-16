import httpx
import pytest


@pytest.mark.anyio
async def test_dashboard_example_exposes_resources_and_custom_pages() -> None:
    from examples.dashboard.main import admin

    app = admin.asgi()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://localhost",
    ) as client:
        dashboard = await client.get("/")
        orders = await client.get("/orders")
        customers = await client.get("/customers")
        activity = await client.get("/activity")
        runbook = await client.get("/runbook")

    assert dashboard.status_code == 200
    assert "Quick access" in dashboard.text
    assert 'href="/orders"' in dashboard.text
    assert 'href="/customers"' in dashboard.text
    assert 'href="/activity"' in dashboard.text
    assert 'href="/runbook"' in dashboard.text

    assert orders.status_code == 200
    assert "ORD-1042" in orders.text
    assert customers.status_code == 200
    assert "Northstar Labs" in customers.text
    assert activity.status_code == 200
    assert "Recent operational activity" in activity.text
    assert runbook.status_code == 200
    assert "Operations runbook" in runbook.text
