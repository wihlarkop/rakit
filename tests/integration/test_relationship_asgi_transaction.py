"""Phase 3B real integration: transaction, commit, fragment, and transient proofs."""

import re
from typing import Any, cast

import httpx
import pytest
from rakit_core.identity import IdentityCodec, RecordIdentity

from .rakit_integration import (
    CommitRecorder,
    IntegrationApp,
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
async def test_combined_graph_save_persists_everything_in_one_transaction(
    integration: tuple[IntegrationApp, dict[str, object]],
    parent: str,
    codec: IdentityCodec,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app, identities = integration
    hedy = codec.encode(cast(RecordIdentity, identities["customer_hedy"]))
    tag_one = codec.encode(cast(RecordIdentity, identities["tag_one"]))
    tag_two = codec.encode(cast(RecordIdentity, identities["tag_two"]))
    line_21 = codec.encode(cast(RecordIdentity, identities["line_21"]))
    line_22 = codec.encode(cast(RecordIdentity, identities["line_22"]))
    line_23 = codec.encode(cast(RecordIdentity, identities["line_23"]))
    attachment = codec.encode(cast(RecordIdentity, identities["attachment_41"]))
    course_one = codec.encode(cast(RecordIdentity, identities["course_one"]))
    customer_prefix = relationship_prefix("customer")
    tags_prefix = relationship_prefix("tags")
    items_prefix = relationship_prefix("line_items")
    attachments_prefix = relationship_prefix("attachments")
    enrollments_prefix = relationship_prefix("enrollments")

    calls: list[dict[str, object]] = []
    original = app.parent_service.update_graph

    async def tracked_update_graph(*args: Any, **kwargs: Any) -> object:
        calls.append(kwargs)
        return await original(*args, **kwargs)

    monkeypatch.setattr(app.parent_service, "update_graph", tracked_update_graph)

    async with client_for(app) as client:
        base = await _edit_payload(app, client, parent)
        token = await _delete_token(app, client, parent, base, line_23)
        order_names = sorted(name for name, _ in base if name.startswith(f"{items_prefix}order__"))
        payload = [
            (name, value)
            for name, value in base
            if not (
                name.startswith(f"{attachments_prefix}update__")
                or name.startswith(f"{attachments_prefix}update_token__")
            )
        ]
        payload = replace_control(payload, "status", "combined")
        payload = replace_control(payload, f"{customer_prefix}set", hedy)
        payload = replace_control(payload, f"{items_prefix}update__{line_21}__sku", "SKU-21X")
        payload = replace_control(
            payload, f"{enrollments_prefix}association__{course_one}__grade", "A+"
        )
        payload = replace_control(payload, order_names[0], line_22)
        payload = replace_control(payload, order_names[1], line_21)
        payload = append_controls(
            payload,
            (f"{tags_prefix}link__{tag_two}", tag_two),
            (f"{tags_prefix}unlink__{tag_one}", tag_one),
            (f"{attachments_prefix}unlink__{attachment}", attachment),
            (f"{items_prefix}delete_intent__{line_23}", "true"),
            (f"{items_prefix}delete__{line_23}", token),
        )
        recorder = CommitRecorder(app.engine)
        saved = await _save(app, client, parent, payload)
        recorder.close(app.engine)

    assert saved.status_code == 303
    assert len(calls) == 1
    assert recorder.commits == 1

    assert (await fetch_orders(app.session_factory)) == [("combined", 2)]
    customer, tags, enrollments = await fetch_order_relationship(app.session_factory)
    assert customer == (3,)
    assert tags == (2,)
    assert enrollments == ((1, "A+"), (2, "A"))
    items = await fetch_line_items(app.session_factory)
    ids = [item[0] for item in items]
    assert 23 not in ids
    assert ids[0] == 22 and ids[1] == 21
    assert items[0][3] < items[1][3]
    assert any(item[1] == "SKU-21X" for item in items)
    async with app.session_factory() as session:
        from .rakit_integration import Attachment

        attachment_row = await session.get(Attachment, 41)
        assert attachment_row is not None and attachment_row.order_id is None


@pytest.mark.anyio
async def test_combined_graph_rollback_restores_everything(
    integration: tuple[IntegrationApp, dict[str, object]],
    parent: str,
    codec: IdentityCodec,
) -> None:
    app, identities = integration
    hedy = codec.encode(cast(RecordIdentity, identities["customer_hedy"]))
    tag_one = codec.encode(cast(RecordIdentity, identities["tag_one"]))
    tag_two = codec.encode(cast(RecordIdentity, identities["tag_two"]))
    line_21 = codec.encode(cast(RecordIdentity, identities["line_21"]))
    line_23 = codec.encode(cast(RecordIdentity, identities["line_23"]))
    attachment = codec.encode(cast(RecordIdentity, identities["attachment_41"]))
    course_one = codec.encode(cast(RecordIdentity, identities["course_one"]))
    customer_prefix = relationship_prefix("customer")
    tags_prefix = relationship_prefix("tags")
    items_prefix = relationship_prefix("line_items")
    attachments_prefix = relationship_prefix("attachments")
    enrollments_prefix = relationship_prefix("enrollments")

    async with client_for(app) as client:
        base = await _edit_payload(app, client, parent)
        token = await _delete_token(app, client, parent, base, line_23)
        payload = [
            (name, value)
            for name, value in base
            if not (
                name.startswith(f"{attachments_prefix}update__")
                or name.startswith(f"{attachments_prefix}update_token__")
            )
        ]
        payload = replace_control(payload, "status", "combined")
        payload = replace_control(payload, f"{customer_prefix}set", hedy)
        payload = replace_control(payload, f"{items_prefix}update__{line_21}__sku", "SKU-21X")
        payload = replace_control(
            payload, f"{enrollments_prefix}association__{course_one}__grade", "A+"
        )
        payload = append_controls(
            payload,
            (f"{tags_prefix}link__{tag_two}", tag_two),
            (f"{tags_prefix}unlink__{tag_one}", tag_one),
            (f"{items_prefix}create__new-combined__sku", "bad-sku"),
            (f"{items_prefix}create__new-combined__quantity", "4"),
            (f"{attachments_prefix}unlink__{attachment}", attachment),
            (f"{items_prefix}delete_intent__{line_23}", "true"),
            (f"{items_prefix}delete__{line_23}", token),
        )
        saved = await _save(app, client, parent, payload)

    assert saved.status_code == 422
    assert (await fetch_orders(app.session_factory)) == [("draft", 1)]
    customer, tags, enrollments = await fetch_order_relationship(app.session_factory)
    assert customer == (1,)
    assert tags == (1,)
    assert enrollments == ((1, "B"), (2, "A"))
    items = await fetch_line_items(app.session_factory)
    assert [item[0] for item in items] == [21, 22, 23]
    assert all(item[1] != "SKU-COMBINED" for item in items)
    assert all(item[1] != "SKU-21X" for item in items)
    assert items[0][4] == 1
    async with app.session_factory() as session:
        from .rakit_integration import Attachment

        attachment_row = await session.get(Attachment, 41)
        assert attachment_row is not None and attachment_row.order_id == 10


@pytest.mark.anyio
async def test_final_save_commits_exactly_once_without_nested_commits(
    integration: tuple[IntegrationApp, dict[str, object]],
    parent: str,
    codec: IdentityCodec,
) -> None:
    app, identities = integration
    line_21 = codec.encode(cast(RecordIdentity, identities["line_21"]))
    items_prefix = relationship_prefix("line_items")

    async with client_for(app) as client:
        base = await _edit_payload(app, client, parent)
        payload = replace_control(base, "status", "committed")
        payload = replace_control(payload, f"{items_prefix}update__{line_21}__sku", "SKU-21-COMMIT")
        recorder = CommitRecorder(app.engine)
        saved = await _save(app, client, parent, payload)
        recorder.close(app.engine)

    assert saved.status_code == 303
    assert recorder.commits == 1
    assert (await fetch_orders(app.session_factory)) == [("committed", 2)]


@pytest.mark.anyio
async def test_fragment_and_intermediate_requests_never_persist(
    integration: tuple[IntegrationApp, dict[str, object]],
    parent: str,
    codec: IdentityCodec,
) -> None:
    app, identities = integration
    line_23 = codec.encode(cast(RecordIdentity, identities["line_23"]))
    items_prefix = relationship_prefix("line_items")

    async with client_for(app) as client:
        base = await _edit_payload(app, client, parent)
        before_orders = await fetch_orders(app.session_factory)
        before_items = await fetch_line_items(app.session_factory)
        before_relationship = await fetch_order_relationship(app.session_factory)

        await client.get(
            f"/orders/{parent}/_relationships/customer/options?q=Ad",
            headers={"HX-Request": "true"},
        )
        await client.post(
            f"/orders/{parent}/_relationships/line_items/page/1",
            content=encode_form(base),
            headers={"Content-Type": "application/x-www-form-urlencoded", "HX-Request": "true"},
        )
        await client.post(
            f"/orders/{parent}/_relationships/line_items/preview",
            content=encode_form(append_controls(base, (f"{items_prefix}delete_preview", line_23))),
            headers={"Content-Type": "application/x-www-form-urlencoded", "HX-Request": "true"},
        )
        confirm_page = await client.post(
            f"/orders/{parent}/_relationships/line_items/preview",
            content=encode_form(append_controls(base, (f"{items_prefix}delete_preview", line_23))),
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        assert confirm_page.status_code == 200
        await client.post(
            f"/orders/{parent}/_relationships/line_items/preview/confirm",
            content=encode_form(
                append_controls(parsed_form(confirm_page.text), ("cancel", "cancel"))
            ),
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )

    assert (await fetch_orders(app.session_factory)) == before_orders
    assert (await fetch_line_items(app.session_factory)) == before_items
    assert (await fetch_order_relationship(app.session_factory)) == before_relationship


@pytest.mark.anyio
async def test_transient_preview_commands_never_become_durable_mutation(
    integration: tuple[IntegrationApp, dict[str, object]],
    parent: str,
    codec: IdentityCodec,
) -> None:
    app, identities = integration
    line_23 = codec.encode(cast(RecordIdentity, identities["line_23"]))
    tag_one = codec.encode(cast(RecordIdentity, identities["tag_one"]))
    items_prefix = relationship_prefix("line_items")
    tags_prefix = relationship_prefix("tags")
    customer_prefix = relationship_prefix("customer")

    async with client_for(app) as client:
        before_items = await fetch_line_items(app.session_factory)
        before_relationship = await fetch_order_relationship(app.session_factory)

        def scalar_only(base: list[tuple[str, str]]) -> list[tuple[str, str]]:
            return [
                (name, value)
                for name, value in base
                if name in {"status", "csrf_token", "submission_token", "concurrency_token"}
            ]

        base = await _edit_payload(app, client, parent)
        delete_only = await _save(
            app,
            client,
            parent,
            [*scalar_only(base), (f"{items_prefix}delete_preview", line_23)],
        )
        assert delete_only.status_code == 303

        base = await _edit_payload(app, client, parent)
        unlink_only = await _save(
            app,
            client,
            parent,
            [*scalar_only(base), (f"{tags_prefix}unlink_preview", tag_one)],
        )
        assert unlink_only.status_code == 303

        base = await _edit_payload(app, client, parent)
        clear_only = await _save(
            app,
            client,
            parent,
            [*scalar_only(base), (f"{customer_prefix}clear_preview", "true")],
        )
        assert clear_only.status_code == 303

        base = await _edit_payload(app, client, parent)
        move_only = await _save(
            app,
            client,
            parent,
            [*scalar_only(base), (f"{items_prefix}move__{line_23}__up", "up")],
        )
        assert move_only.status_code == 422

        base = await _edit_payload(app, client, parent)
        intent_without_confirmation = await _save(
            app,
            client,
            parent,
            [*scalar_only(base), (f"{items_prefix}delete_intent__{line_23}", "true")],
        )
        assert intent_without_confirmation.status_code == 422

    assert (await fetch_line_items(app.session_factory)) == before_items
    assert (await fetch_order_relationship(app.session_factory)) == before_relationship
