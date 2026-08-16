"""Phase 3B real integration: normalized response and error contracts."""

from typing import cast

import httpx
import pytest
from rakit_core.identity import IdentityCodec, RecordIdentity
from sqlalchemy import update

from .rakit_integration import (
    IntegrationApp,
    LineItem,
    client_for,
    encode_form,
    fetch_line_items,
    fetch_orders,
    parsed_form,
    relationship_prefix,
    replace_control,
)


async def _edit_payload(app: IntegrationApp, client: httpx.AsyncClient, parent: str):
    edit = await client.get(f"/orders/{parent}/edit")
    assert edit.status_code == 200
    return parsed_form(edit.text)


async def _save(
    app: IntegrationApp,
    client: httpx.AsyncClient,
    parent: str,
    payload: list[tuple[str, str]],
) -> httpx.Response:
    return await client.post(
        f"/orders/{parent}/edit",
        content=encode_form(payload),
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        follow_redirects=False,
    )


@pytest.mark.anyio
async def test_scalar_validation_error_renders_admin_shell(
    integration: tuple[IntegrationApp, dict[str, object]],
    parent: str,
) -> None:
    app, _ = integration
    async with client_for(app) as client:
        base = await _edit_payload(app, client, parent)
        saved = await _save(app, client, parent, replace_control(base, "status", ""))

    assert saved.status_code == 422
    assert "<!doctype html>" in saved.text
    assert "There are problems with this form" in saved.text
    assert 'name="status"' in saved.text
    assert (await fetch_orders(app.session_factory)) == [("draft", 1)]


@pytest.mark.anyio
async def test_stale_concurrency_returns_normalized_conflict(
    integration: tuple[IntegrationApp, dict[str, object]],
    parent: str,
    codec: IdentityCodec,
) -> None:
    app, identities = integration
    line_21 = codec.encode(cast(RecordIdentity, identities["line_21"]))
    prefix = relationship_prefix("line_items")
    async with client_for(app) as client:
        base = await _edit_payload(app, client, parent)
        async with app.session_factory() as session:
            await session.execute(
                update(LineItem)
                .where(LineItem.id == 21)
                .values(sku="directly-changed", version=LineItem.version + 1)
            )
            await session.commit()
        saved = await _save(
            app,
            client,
            parent,
            replace_control(
                replace_control(base, "status", "should-not-persist"),
                f"{prefix}update__{line_21}__sku",
                "SKU-021-STALE",
            ),
        )

    assert saved.status_code == 409
    assert "<!doctype html>" in saved.text
    assert (await fetch_orders(app.session_factory)) == [("draft", 1)]
    items = await fetch_line_items(app.session_factory)
    assert items[0][1] == "directly-changed"


@pytest.mark.anyio
async def test_malformed_relationship_transport_fails_closed(
    integration: tuple[IntegrationApp, dict[str, object]],
    parent: str,
) -> None:
    app, _ = integration
    async with client_for(app) as client:
        base = await _edit_payload(app, client, parent)
        saved = await _save(
            app,
            client,
            parent,
            [
                *replace_control(base, "status", "should-not-persist"),
                ("__rakit_rel__unknown__control", "x"),
            ],
        )

    assert saved.status_code == 400
    assert (await fetch_orders(app.session_factory)) == [("draft", 1)]


@pytest.mark.anyio
async def test_duplicate_control_transport_fails_closed(
    integration: tuple[IntegrationApp, dict[str, object]],
    parent: str,
) -> None:
    app, _ = integration
    async with client_for(app) as client:
        base = await _edit_payload(app, client, parent)
        payload = replace_control(base, "status", "should-not-persist")
        saved = await _save(app, client, parent, [*payload, ("status", "dup")])

    assert saved.status_code == 400
    assert (await fetch_orders(app.session_factory)) == [("draft", 1)]
