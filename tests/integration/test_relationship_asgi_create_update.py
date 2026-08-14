"""Phase 3B real integration: parent create/update and child create/update proofs."""

from typing import Any, cast

from rakit_core.identity import IdentityCodec, RecordIdentity
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from .rakit_integration import (
    IntegrationApp,
    LineItem,
    Order,
    append_controls,
    client_for,
    encode_form,
    fetch_line_items,
    fetch_orders,
    parsed_form,
    relationship_prefix,
    replace_control,
)


async def _fetch_created_order(
    factory: async_sessionmaker[Any],
) -> tuple[int, str, int, list[tuple[int, str, int]]]:
    async with factory() as session:
        orders = (await session.scalars(select(Order).order_by(Order.id))).all()
        order = orders[-1]
        items = (
            await session.scalars(
                select(LineItem).where(LineItem.order_id == order.id).order_by(LineItem.id)
            )
        ).all()
        return (
            order.id,
            order.status,
            order.version,
            [(item.id, item.sku, item.quantity) for item in items],
        )


async def test_create_persists_parent_and_required_fk_child_atomically(
    integration: tuple[IntegrationApp, dict[str, object]],
) -> None:
    app, _ = integration
    async with client_for(app) as client:
        form = await client.get("/orders/new")
        assert form.status_code == 200
        payload = [
            *parsed_form(form.text),
            (f"{relationship_prefix('line_items')}create__new-draft__sku", "SKU-NEW"),
            (f"{relationship_prefix('line_items')}create__new-draft__quantity", "5"),
        ]
        payload = replace_control(payload, "status", "shipped")
        created = await client.post(
            "/orders/new",
            content=encode_form(payload),
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            follow_redirects=False,
        )

    assert created.status_code == 303
    order_id, status, version, items = await _fetch_created_order(app.session_factory)
    assert status == "shipped"
    assert version == 1
    assert items == [(order_id + 14, "SKU-NEW", 5)] or (
        len(items) == 1 and items[0][1:] == ("SKU-NEW", 5)
    )
    assert order_id != 10
    assert items[0][0] > 23


async def test_update_persists_parent_scalar_and_child_update_together(
    integration: tuple[IntegrationApp, dict[str, object]],
    parent: str,
    codec: IdentityCodec,
) -> None:
    app, identities = integration
    line_21 = codec.encode(cast(RecordIdentity, identities["line_21"]))
    prefix = relationship_prefix("line_items")
    async with client_for(app) as client:
        edit = await client.get(f"/orders/{parent}/edit")
        payload = replace_control(parsed_form(edit.text), "status", "confirmed")
        payload = replace_control(payload, f"{prefix}update__{line_21}__sku", "SKU-021-CHANGED")
        saved = await client.post(
            f"/orders/{parent}/edit",
            content=encode_form(payload),
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            follow_redirects=False,
        )

    assert saved.status_code == 303
    assert (await fetch_orders(app.session_factory)) == [("confirmed", 2)]
    items = await fetch_line_items(app.session_factory)
    assert items[0][:4] == (21, "SKU-021-CHANGED", 1, 0)
    assert items[0][4] == 2


async def test_invalid_child_rolls_back_parent_scalar_change(
    integration: tuple[IntegrationApp, dict[str, object]],
    parent: str,
    codec: IdentityCodec,
) -> None:
    app, identities = integration
    line_21 = codec.encode(cast(RecordIdentity, identities["line_21"]))
    prefix = relationship_prefix("line_items")
    async with client_for(app) as client:
        edit = await client.get(f"/orders/{parent}/edit")
        payload = replace_control(parsed_form(edit.text), "status", "should-not-persist")
        payload = replace_control(payload, f"{prefix}update__{line_21}__sku", "bad-sku")
        saved = await client.post(
            f"/orders/{parent}/edit",
            content=encode_form(payload),
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            follow_redirects=False,
        )

    assert saved.status_code == 422
    assert "There are problems with this form" in saved.text
    assert (await fetch_orders(app.session_factory)) == [("draft", 1)]
    items = await fetch_line_items(app.session_factory)
    assert items[0][:4] == (21, "SKU-021", 1, 1)
    assert items[0][4] == 1


async def test_child_create_through_inline_form_persists_without_nested_commit(
    integration: tuple[IntegrationApp, dict[str, object]],
    parent: str,
) -> None:
    app, _ = integration
    prefix = relationship_prefix("line_items")
    async with client_for(app) as client:
        edit = await client.get(f"/orders/{parent}/edit")
        payload = [
            (name, value)
            for name, value in parsed_form(edit.text)
            if not name.startswith(f"{prefix}order__")
        ]
        payload = append_controls(
            payload,
            (f"{prefix}create__new-web__sku", "SKU-WEB"),
            (f"{prefix}create__new-web__quantity", "7"),
        )
        saved = await client.post(
            f"/orders/{parent}/edit",
            content=encode_form(payload),
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            follow_redirects=False,
        )

    assert saved.status_code == 303
    items = await fetch_line_items(app.session_factory)
    assert any(item[1] == "SKU-WEB" and item[2] == 7 for item in items)
    created = next(item for item in items if item[1] == "SKU-WEB")
    async with app.session_factory() as session:
        item = await session.get(LineItem, created[0])
        assert item is not None
        assert item.order_id == 10


async def test_child_update_preserves_child_concurrency_contract(
    integration: tuple[IntegrationApp, dict[str, object]],
    parent: str,
    codec: IdentityCodec,
) -> None:
    app, identities = integration
    line_23 = codec.encode(cast(RecordIdentity, identities["line_23"]))
    prefix = relationship_prefix("line_items")
    async with client_for(app) as client:
        edit = await client.get(f"/orders/{parent}/edit")
        payload = replace_control(
            parsed_form(edit.text), f"{prefix}update__{line_23}__quantity", "99"
        )
        saved = await client.post(
            f"/orders/{parent}/edit",
            content=encode_form(payload),
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            follow_redirects=False,
        )

    assert saved.status_code == 303
    items = await fetch_line_items(app.session_factory)
    assert items[2][:4] == (23, "SKU-023", 99, 2)
    assert items[2][4] == 2
