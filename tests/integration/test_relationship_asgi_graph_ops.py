"""Phase 3B real integration: relationship graph operations through real HTTP."""

import re
from typing import cast

import httpx
import pytest
from rakit_core.identity import IdentityCodec, RecordIdentity

from .rakit_integration import (
    CommitRecorder,
    IntegrationApp,
    LineItem,
    Order,
    append_controls,
    client_for,
    encode_form,
    fetch_line_items,
    fetch_order_relationship,
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


async def _delete_token(
    app: IntegrationApp,
    client: httpx.AsyncClient,
    parent: str,
    base: list[tuple[str, str]],
    identity: str,
) -> str:
    prefix = relationship_prefix("line_items")
    preview = await client.post(
        f"/orders/{parent}/_relationships/line_items/preview",
        content=encode_form(append_controls(base, (f"{prefix}delete_preview", identity))),
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "HX-Request": "true",
        },
    )
    assert preview.status_code == 200
    confirmation = re.search(r'data-rakit-confirmation="([^"]+)"', preview.text)
    assert confirmation is not None
    return confirmation.group(1)


@pytest.mark.anyio
async def test_to_one_set_persists_new_customer(
    integration: tuple[IntegrationApp, dict[str, object]],
    parent: str,
    codec: IdentityCodec,
) -> None:
    app, identities = integration
    hedy = codec.encode(cast(RecordIdentity, identities["customer_hedy"]))
    prefix = relationship_prefix("customer")
    async with client_for(app) as client:
        payload = replace_control(await _edit_payload(app, client, parent), f"{prefix}set", hedy)
        saved = await _save(app, client, parent, payload)

    assert saved.status_code == 303
    assert (await fetch_order_relationship(app.session_factory))[0] == (3,)


@pytest.mark.anyio
async def test_to_one_clear_persists_null_relationship(
    integration: tuple[IntegrationApp, dict[str, object]],
    parent: str,
) -> None:
    app, _ = integration
    prefix = relationship_prefix("customer")
    async with client_for(app) as client:
        payload = replace_control(await _edit_payload(app, client, parent), f"{prefix}set", "")
        payload = append_controls(payload, (f"{prefix}clear", "true"))
        saved = await _save(app, client, parent, payload)

    assert saved.status_code == 303
    assert (await fetch_order_relationship(app.session_factory))[0] == (None,)


@pytest.mark.anyio
async def test_many_to_many_link_and_unlink_are_explicit(
    integration: tuple[IntegrationApp, dict[str, object]],
    parent: str,
    codec: IdentityCodec,
) -> None:
    app, identities = integration
    tag_two = codec.encode(cast(RecordIdentity, identities["tag_two"]))
    tag_one = codec.encode(cast(RecordIdentity, identities["tag_one"]))
    prefix = relationship_prefix("tags")

    async with client_for(app) as client:
        base = await _edit_payload(app, client, parent)
        linked = await _save(
            app,
            client,
            parent,
            append_controls(base, (f"{prefix}link__{tag_two}", tag_two)),
        )
        assert linked.status_code == 303
        assert (await fetch_order_relationship(app.session_factory))[1] == (1, 2)

        base = await _edit_payload(app, client, parent)
        unlinked = await _save(
            app,
            client,
            parent,
            append_controls(base, (f"{prefix}unlink__{tag_one}", tag_one)),
        )
        assert unlinked.status_code == 303
        assert (await fetch_order_relationship(app.session_factory))[1] == (2,)


@pytest.mark.anyio
async def test_omission_does_not_unlink_off_page_members(
    integration: tuple[IntegrationApp, dict[str, object]],
    parent: str,
) -> None:
    app, _ = integration
    async with client_for(app) as client:
        payload = replace_control(await _edit_payload(app, client, parent), "status", "touched")
        saved = await _save(app, client, parent, payload)

    assert saved.status_code == 303
    assert (await fetch_order_relationship(app.session_factory))[1] == (1,)


@pytest.mark.anyio
async def test_unlink_keeps_child_row_while_delete_removes_it(
    integration: tuple[IntegrationApp, dict[str, object]],
    parent: str,
    codec: IdentityCodec,
) -> None:
    app, identities = integration
    attachment = codec.encode(cast(RecordIdentity, identities["attachment_41"]))
    line_23 = codec.encode(cast(RecordIdentity, identities["line_23"]))
    attachments_prefix = relationship_prefix("attachments")
    items_prefix = relationship_prefix("line_items")

    async with client_for(app) as client:
        base = await _edit_payload(app, client, parent)
        unlink_payload = [
            (name, value)
            for name, value in base
            if not (
                name.startswith(f"{attachments_prefix}update__")
                or name.startswith(f"{attachments_prefix}update_token__")
            )
        ]
        unlinked = await _save(
            app,
            client,
            parent,
            append_controls(
                unlink_payload,
                (f"{attachments_prefix}unlink__{attachment}", attachment),
            ),
        )
        assert unlinked.status_code == 303
        async with app.session_factory() as session:
            from .rakit_integration import Attachment

            row = await session.get(Attachment, 41)
            assert row is not None and row.order_id is None

        base = await _edit_payload(app, client, parent)
        preview = await client.post(
            f"/orders/{parent}/_relationships/line_items/preview",
            content=encode_form(append_controls(base, (f"{items_prefix}delete_preview", line_23))),
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "HX-Request": "true",
            },
        )
        confirmation = re.search(r'data-rakit-confirmation="([^"]+)"', preview.text)
        assert preview.status_code == 200
        assert confirmation is not None
        deleted = await _save(
            app,
            client,
            parent,
            append_controls(
                base,
                (f"{items_prefix}delete_intent__{line_23}", "true"),
                (f"{items_prefix}delete__{line_23}", confirmation.group(1)),
            ),
        )
        assert deleted.status_code == 303

    items = await fetch_line_items(app.session_factory)
    assert [item[0] for item in items] == [21, 22]
    async with app.session_factory() as session:
        row = await session.get(LineItem, 23)
        assert row is None


@pytest.mark.anyio
async def test_delete_destructive_flow_preview_confirmation_and_persistence(
    integration: tuple[IntegrationApp, dict[str, object]],
    parent: str,
    codec: IdentityCodec,
) -> None:
    app, identities = integration
    line_23 = codec.encode(cast(RecordIdentity, identities["line_23"]))
    prefix = relationship_prefix("line_items")

    async with client_for(app) as client:
        base = await _edit_payload(app, client, parent)
        before = await fetch_line_items(app.session_factory)
        preview = await client.post(
            f"/orders/{parent}/_relationships/line_items/preview",
            content=encode_form(append_controls(base, (f"{prefix}delete_preview", line_23))),
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "HX-Request": "true",
            },
        )
        assert preview.status_code == 200
        confirmation = re.search(r'data-rakit-confirmation="([^"]+)"', preview.text)
        assert confirmation is not None
        assert (await fetch_line_items(app.session_factory)) == before

        saved = await _save(
            app,
            client,
            parent,
            append_controls(
                base,
                (f"{prefix}delete_intent__{line_23}", "true"),
                (f"{prefix}delete__{line_23}", confirmation.group(1)),
            ),
        )
        assert saved.status_code == 303

    items = await fetch_line_items(app.session_factory)
    assert [item[0] for item in items] == [21, 22]


@pytest.mark.anyio
async def test_forged_delete_confirmation_fails_closed(
    integration: tuple[IntegrationApp, dict[str, object]],
    parent: str,
    codec: IdentityCodec,
) -> None:
    app, identities = integration
    line_22 = codec.encode(cast(RecordIdentity, identities["line_22"]))
    prefix = relationship_prefix("line_items")

    async with client_for(app) as client:
        base = await _edit_payload(app, client, parent)
        saved = await _save(
            app,
            client,
            parent,
            append_controls(
                replace_control(base, "status", "should-not-persist"),
                (f"{prefix}delete_intent__{line_22}", "true"),
                (f"{prefix}delete__{line_22}", "forged-token"),
            ),
        )

    assert saved.status_code == 400
    assert (await fetch_orders(app.session_factory)) == [("draft", 1)]
    assert [item[0] for item in await fetch_line_items(app.session_factory)] == [21, 22, 23]


@pytest.mark.anyio
async def test_delete_confirmation_for_wrong_target_fails_closed(
    integration: tuple[IntegrationApp, dict[str, object]],
    parent: str,
    codec: IdentityCodec,
) -> None:
    app, identities = integration
    line_21 = codec.encode(cast(RecordIdentity, identities["line_21"]))
    line_22 = codec.encode(cast(RecordIdentity, identities["line_22"]))
    prefix = relationship_prefix("line_items")

    async with client_for(app) as client:
        base = await _edit_payload(app, client, parent)
        preview = await client.post(
            f"/orders/{parent}/_relationships/line_items/preview",
            content=encode_form(append_controls(base, (f"{prefix}delete_preview", line_21))),
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "HX-Request": "true",
            },
        )
        confirmation = re.search(r'data-rakit-confirmation="([^"]+)"', preview.text)
        assert confirmation is not None
        saved = await _save(
            app,
            client,
            parent,
            append_controls(
                replace_control(base, "status", "should-not-persist"),
                (f"{prefix}delete_intent__{line_22}", "true"),
                (f"{prefix}delete__{line_22}", confirmation.group(1)),
            ),
        )

    assert saved.status_code == 400
    assert (await fetch_orders(app.session_factory)) == [("draft", 1)]
    assert [item[0] for item in await fetch_line_items(app.session_factory)] == [21, 22, 23]


@pytest.mark.anyio
async def test_stale_child_concurrency_rolls_back_entire_parent_graph(
    integration: tuple[IntegrationApp, dict[str, object]],
    parent: str,
    codec: IdentityCodec,
) -> None:
    app, identities = integration
    line_21 = codec.encode(cast(RecordIdentity, identities["line_21"]))
    prefix = relationship_prefix("line_items")

    async with client_for(app) as client:
        base = await _edit_payload(app, client, parent)
        from sqlalchemy import update

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

    assert saved.status_code in (409, 422)
    assert (await fetch_orders(app.session_factory)) == [("draft", 1)]
    items = await fetch_line_items(app.session_factory)
    assert items[0][:4] == (21, "directly-changed", 1, 1)
    assert items[0][4] == 2


@pytest.mark.anyio
async def test_off_scope_target_is_rejected_without_partial_persistence(
    integration: tuple[IntegrationApp, dict[str, object]],
    parent: str,
    codec: IdentityCodec,
) -> None:
    app, identities = integration
    off_scope = codec.encode(cast(RecordIdentity, identities["customer_grace_off_scope"]))
    prefix = relationship_prefix("customer")

    async with client_for(app) as client:
        base = await _edit_payload(app, client, parent)
        saved = await _save(
            app,
            client,
            parent,
            replace_control(
                replace_control(base, "status", "should-not-persist"),
                f"{prefix}set",
                off_scope,
            ),
        )

    assert saved.status_code == 404
    assert (await fetch_orders(app.session_factory)) == [("draft", 1)]
    assert (await fetch_order_relationship(app.session_factory))[0] == (1,)


@pytest.mark.anyio
async def test_forged_target_identity_is_rejected_without_persistence(
    integration: tuple[IntegrationApp, dict[str, object]],
    parent: str,
) -> None:
    app, _ = integration
    prefix = relationship_prefix("customer")

    async with client_for(app) as client:
        base = await _edit_payload(app, client, parent)
        saved = await _save(
            app,
            client,
            parent,
            replace_control(
                replace_control(base, "status", "should-not-persist"),
                f"{prefix}set",
                "not-a-valid-identity",
            ),
        )

    assert saved.status_code == 400
    assert (await fetch_orders(app.session_factory)) == [("draft", 1)]
    assert (await fetch_order_relationship(app.session_factory))[0] == (1,)


@pytest.mark.anyio
async def test_reorder_persists_positions_and_rejects_invalid_sequences(
    integration: tuple[IntegrationApp, dict[str, object]],
    parent: str,
    codec: IdentityCodec,
) -> None:
    app, identities = integration
    line_21 = codec.encode(cast(RecordIdentity, identities["line_21"]))
    line_22 = codec.encode(cast(RecordIdentity, identities["line_22"]))
    prefix = relationship_prefix("line_items")

    async with client_for(app) as client:
        base = await _edit_payload(app, client, parent)
        order_names = sorted(name for name, _ in base if name.startswith(f"{prefix}order__"))
        assert len(order_names) == 3
        swapped = dict(base)
        swapped[order_names[0]] = line_22
        swapped[order_names[1]] = line_21
        saved = await _save(app, client, parent, [(name, value) for name, value in swapped.items()])
        assert saved.status_code == 303

    items = await fetch_line_items(app.session_factory)
    assert [(item[0], item[3]) for item in items] == [(22, 0), (21, 1), (23, 2)]

    async with client_for(app) as client:
        base = await _edit_payload(app, client, parent)
        incomplete = [
            (name, value) for name, value in base if not name.startswith(f"{prefix}order__")
        ]
        incomplete.append((order_names[0], line_21))
        incomplete.append((order_names[1], line_22))
        rejected = await _save(app, client, parent, incomplete)
        assert rejected.status_code == 422

        duplicate = [
            (name, value) for name, value in base if not name.startswith(f"{prefix}order__")
        ]
        duplicate.append((order_names[0], line_21))
        duplicate.append((order_names[1], line_21))
        duplicate.append((order_names[2], line_22))
        rejected_duplicate = await _save(app, client, parent, duplicate)
        assert rejected_duplicate.status_code == 422

        unknown = [(name, value) for name, value in base if not name.startswith(f"{prefix}order__")]
        unknown.append((order_names[0], line_21))
        unknown.append((order_names[1], line_22))
        unknown.append(
            (
                order_names[2],
                codec.encode(RecordIdentity(values={"id": 999})),
            )
        )
        rejected_unknown = await _save(app, client, parent, unknown)
        assert rejected_unknown.status_code == 422

    assert [(item[0], item[3]) for item in await fetch_line_items(app.session_factory)] == [
        (22, 0),
        (21, 1),
        (23, 2),
    ]


@pytest.mark.anyio
async def test_oversized_reorder_fails_closed(
    integration: tuple[IntegrationApp, dict[str, object]],
    parent: str,
    codec: IdentityCodec,
) -> None:
    app, identities = integration
    prefix = relationship_prefix("line_items")
    async with app.session_factory() as session:
        order = await session.get(Order, 10)
        assert order is not None
        await session.refresh(order, attribute_names=["line_items"])
        for index in range(24, 32):
            order.line_items.append(
                LineItem(id=index, sku=f"SKU-{index}", quantity=1, position=index - 20)
            )
        await session.commit()

    async with client_for(app) as client:
        base = await _edit_payload(app, client, parent)
        order_names = sorted(name for name, _ in base if name.startswith(f"{prefix}order__"))
        assert len(order_names) == 0  # reorder unavailable above the safe bound
        payload = [(name, value) for name, value in base if not name.startswith(f"{prefix}order__")]
        payload.append(
            (
                f"{prefix}order__0000",
                codec.encode(cast(RecordIdentity, identities["line_21"])),
            )
        )
        rejected = await _save(app, client, parent, payload)
        assert rejected.status_code == 422


@pytest.mark.anyio
async def test_association_scalar_update_persists_and_unknown_column_is_rejected(
    integration: tuple[IntegrationApp, dict[str, object]],
    parent: str,
    codec: IdentityCodec,
) -> None:
    app, identities = integration
    course_one = codec.encode(cast(RecordIdentity, identities["course_one"]))
    prefix = relationship_prefix("enrollments")

    async with client_for(app) as client:
        base = await _edit_payload(app, client, parent)
        updated = await _save(
            app,
            client,
            parent,
            replace_control(base, f"{prefix}association__{course_one}__grade", "A+"),
        )
        assert updated.status_code == 303

        base = await _edit_payload(app, client, parent)
        rejected = await _save(
            app,
            client,
            parent,
            append_controls(
                base,
                (f"{prefix}association__{course_one}__secret", "x"),
            ),
        )
        assert rejected.status_code == 422

    assert (await fetch_order_relationship(app.session_factory))[2] == (
        (1, "A+"),
        (2, "A"),
    )


@pytest.mark.anyio
async def test_delete_and_reorder_survive_in_one_save(
    integration: tuple[IntegrationApp, dict[str, object]],
    parent: str,
    codec: IdentityCodec,
) -> None:
    app, identities = integration
    line_21 = codec.encode(cast(RecordIdentity, identities["line_21"]))
    line_22 = codec.encode(cast(RecordIdentity, identities["line_22"]))
    line_23 = codec.encode(cast(RecordIdentity, identities["line_23"]))
    prefix = relationship_prefix("line_items")

    async with client_for(app) as client:
        base = await _edit_payload(app, client, parent)
        order_names = sorted(name for name, _ in base if name.startswith(f"{prefix}order__"))
        assert [value for name, value in base if name == order_names[0]] == [line_21]
        token = await _delete_token(app, client, parent, base, line_23)
        payload = dict(base)
        payload[order_names[0]] = line_22
        payload[order_names[1]] = line_21
        payload = [(name, value) for name, value in payload.items()]
        payload = append_controls(
            payload,
            (f"{prefix}delete_intent__{line_23}", "true"),
            (f"{prefix}delete__{line_23}", token),
        )
        recorder = CommitRecorder(app.engine)
        saved = await _save(app, client, parent, payload)
        recorder.close(app.engine)

    assert saved.status_code == 303
    assert recorder.commits == 1
    items = await fetch_line_items(app.session_factory)
    assert [item[0] for item in items] == [22, 21]
    assert items[0][3] < items[1][3]
    assert all(item[0] != 23 for item in items)


@pytest.mark.anyio
async def test_invalid_reorder_with_pending_delete_fails_closed(
    integration: tuple[IntegrationApp, dict[str, object]],
    parent: str,
    codec: IdentityCodec,
) -> None:
    app, identities = integration
    line_21 = codec.encode(cast(RecordIdentity, identities["line_21"]))
    line_22 = codec.encode(cast(RecordIdentity, identities["line_22"]))
    line_23 = codec.encode(cast(RecordIdentity, identities["line_23"]))
    prefix = relationship_prefix("line_items")

    async with client_for(app) as client:
        base = await _edit_payload(app, client, parent)
        order_names = sorted(name for name, _ in base if name.startswith(f"{prefix}order__"))
        token = await _delete_token(app, client, parent, base, line_23)

        def with_delete(values: dict[str, str]) -> list[tuple[str, str]]:
            return append_controls(
                [(name, value) for name, value in values.items()],
                (f"{prefix}delete_intent__{line_23}", "true"),
                (f"{prefix}delete__{line_23}", token),
            )

        duplicate = dict(base)
        duplicate[order_names[0]] = line_21
        duplicate[order_names[1]] = line_21
        duplicate[order_names[2]] = line_22
        rejected_duplicate = await _save(app, client, parent, with_delete(duplicate))
        assert rejected_duplicate.status_code == 422

        incomplete = [
            (name, value) for name, value in base if not name.startswith(f"{prefix}order__")
        ]
        incomplete.append((order_names[0], line_21))
        incomplete.append((order_names[1], line_22))
        rejected_incomplete = await _save(
            app,
            client,
            parent,
            append_controls(
                incomplete,
                (f"{prefix}delete_intent__{line_23}", "true"),
                (f"{prefix}delete__{line_23}", token),
            ),
        )
        assert rejected_incomplete.status_code == 422

        forged = [(name, value) for name, value in base if not name.startswith(f"{prefix}order__")]
        forged.append((order_names[0], line_21))
        forged.append((order_names[1], line_22))
        forged.append((order_names[2], "not-a-valid-identity"))
        rejected_forged = await _save(
            app,
            client,
            parent,
            append_controls(
                forged,
                (f"{prefix}delete_intent__{line_23}", "true"),
                (f"{prefix}delete__{line_23}", token),
            ),
        )
        assert rejected_forged.status_code == 400

    items = await fetch_line_items(app.session_factory)
    assert [item[0] for item in items] == [21, 22, 23]
    assert items[2][4] == 1
