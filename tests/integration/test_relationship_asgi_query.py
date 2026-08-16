"""Phase 3B real integration: bounded pagination, N+1 guard, and target scope."""

import httpx
import pytest

from .rakit_integration import (
    IntegrationApp,
    LineItem,
    Order,
    StatementRecorder,
    client_for,
    encode_form,
    parsed_form,
)


async def _edit_payload(app: IntegrationApp, client: httpx.AsyncClient, parent: str):
    edit = await client.get(f"/orders/{parent}/edit")
    assert edit.status_code == 200
    return parsed_form(edit.text)


@pytest.mark.anyio
async def test_editor_pagination_is_bounded_at_the_adapter(
    integration: tuple[IntegrationApp, dict[str, object]],
    parent: str,
) -> None:
    app, identities = integration

    async with app.session_factory() as session:
        order = await session.get(Order, 10)
        assert order is not None
        await session.refresh(order, attribute_names=["line_items"])
        for index in range(24, 34):
            order.line_items.append(
                LineItem(id=index, sku=f"SKU-{index}", quantity=1, position=index - 20)
            )
        await session.commit()

    async with client_for(app) as client:
        base = await _edit_payload(app, client, parent)
        recorder = StatementRecorder(app.engine)
        page = await client.post(
            f"/orders/{parent}/_relationships/line_items/page/1",
            content=encode_form(base),
            headers={"Content-Type": "application/x-www-form-urlencoded", "HX-Request": "true"},
        )
        recorder.close(app.engine)

    assert page.status_code == 200
    assert "Page 1" in page.text
    assert "Next" in page.text
    assert page.text.count("data-rakit-row=") == 12
    row_queries = [
        statement
        for statement in recorder.statements
        if "integration_line_items" in statement and "LIMIT" in statement
    ]
    assert row_queries
    assert any("OFFSET" in statement for statement in row_queries)
    assert any("position" in statement for statement in row_queries)


@pytest.mark.anyio
async def test_editor_query_growth_is_constant_per_row(
    integration: tuple[IntegrationApp, dict[str, object]],
    parent: str,
) -> None:
    app, identities = integration

    def count_edit_statements(client: httpx.AsyncClient, parent: str) -> int:
        return 0

    async with client_for(app) as client:
        edit = await client.get(f"/orders/{parent}/edit")
        assert edit.status_code == 200
        recorder = StatementRecorder(app.engine)
        await client.get(f"/orders/{parent}/edit")
        recorder.close(app.engine)
        small = len(recorder.statements)

    async with app.session_factory() as session:
        order = await session.get(Order, 10)
        assert order is not None
        await session.refresh(order, attribute_names=["line_items"])
        for index in range(24, 34):
            order.line_items.append(
                LineItem(id=index, sku=f"SKU-{index}", quantity=1, position=index - 20)
            )
        await session.commit()

    async with client_for(app) as client:
        recorder = StatementRecorder(app.engine)
        await client.get(f"/orders/{parent}/edit")
        recorder.close(app.engine)
        large = len(recorder.statements)

    # 3 rows vs 13 rows must not grow the statement count per row.
    assert large - small < 8


@pytest.mark.anyio
async def test_autocomplete_applies_target_scope_before_search(
    integration: tuple[IntegrationApp, dict[str, object]],
    parent: str,
) -> None:
    app, _ = integration
    async with client_for(app) as client:
        visible = await client.get(
            f"/orders/{parent}/_relationships/customer/options?q=Ad",
            headers={"HX-Request": "true"},
        )
        off_scope = await client.get(
            f"/orders/{parent}/_relationships/customer/options?q=Gra",
            headers={"HX-Request": "true"},
        )
        empty = await client.get(
            f"/orders/{parent}/_relationships/customer/options?q=Zzz",
            headers={"HX-Request": "true"},
        )

    assert visible.status_code == 200
    assert "Ada" in visible.text
    assert "Grace" not in visible.text
    assert off_scope.status_code == 200
    assert "Grace" not in off_scope.text
    assert empty.status_code == 200
    assert "Candidate" not in empty.text
