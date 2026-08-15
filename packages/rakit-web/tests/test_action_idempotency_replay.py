"""Focused regression coverage for action idempotency receipt replay."""

import json

from rakit_core.actions import ActionRedirect, ActionRefresh, ActionRendered, ActionSuccess
from rakit_core.idempotency import OperationReceipt
from rakit_web.action_routes import _action_result_receipt, _completed_action_response
from starlette.requests import Request
from starlette.types import Scope


def _request(*, htmx: bool = False) -> Request:
    headers: list[tuple[bytes, bytes]] = []
    if htmx:
        headers.append((b"hx-request", b"true"))
    scope: Scope = {
        "type": "http",
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": "/orders/_actions/example",
        "raw_path": b"/orders/_actions/example",
        "query_string": b"",
        "headers": headers,
        "client": ("127.0.0.1", 12345),
        "server": ("test", 80),
    }
    return Request(scope)


def test_success_receipt_omits_arbitrary_payload_and_replays_message() -> None:
    receipt = _action_result_receipt(
        ActionSuccess(payload={"secret": "must-not-persist"}, message="Order updated"),
        operation_id="1",
        fallback_location="/orders",
    )

    assert receipt.result_kind == "success"
    assert receipt.redirect_route == "/orders"
    assert receipt.payload is not None
    assert receipt.payload == {"message": "Order updated"}
    assert "secret" not in receipt.payload

    normal = _completed_action_response(_request(), receipt, fallback_location="/fallback")
    assert normal.status_code == 303
    assert normal.headers["location"] == "/orders"

    htmx = _completed_action_response(_request(htmx=True), receipt, fallback_location="/fallback")
    assert htmx.status_code == 204
    trigger = json.loads(htmx.headers["hx-trigger"])
    assert trigger["rakit:toast"] == {"message": "Order updated"}
    assert trigger["rakit:refresh"] == {"targets": ["rakit:action-refresh"]}


def test_redirect_receipt_replays_normal_and_htmx_semantics() -> None:
    receipt = _action_result_receipt(
        ActionRedirect(location="/exports/42", message="Export ready"),
        operation_id="2",
        fallback_location="/orders",
    )

    assert receipt.result_kind == "redirect"
    assert receipt.redirect_route == "/exports/42"
    assert receipt.payload == {"message": "Export ready"}

    normal = _completed_action_response(_request(), receipt, fallback_location="/orders")
    assert normal.status_code == 303
    assert normal.headers["location"] == "/exports/42"

    htmx = _completed_action_response(_request(htmx=True), receipt, fallback_location="/orders")
    assert htmx.status_code == 204
    assert htmx.headers["hx-redirect"] == "/exports/42"


def test_refresh_receipt_replays_normal_and_htmx_semantics() -> None:
    receipt = _action_result_receipt(
        ActionRefresh(target="orders:list", message="Orders refreshed"),
        operation_id="3",
        fallback_location="/orders",
    )

    assert receipt.result_kind == "refresh"
    assert receipt.redirect_route == "/orders"
    assert receipt.payload == {"target": "orders:list", "message": "Orders refreshed"}

    normal = _completed_action_response(_request(), receipt, fallback_location="/fallback")
    assert normal.status_code == 303
    assert normal.headers["location"] == "/orders"

    htmx = _completed_action_response(_request(htmx=True), receipt, fallback_location="/fallback")
    assert htmx.status_code == 204
    trigger = json.loads(htmx.headers["hx-trigger"])
    assert trigger["rakit:refresh"] == {"targets": ["orders:list"]}
    assert trigger["rakit:toast"] == {"message": "Orders refreshed"}


def test_rendered_receipt_does_not_persist_trusted_html_or_payload() -> None:
    receipt = _action_result_receipt(
        ActionRendered(
            fragment="<strong>private fragment</strong>",
            payload={"secret": "must-not-persist"},
            message="Rendered",
        ),
        operation_id="4",
        fallback_location="/orders",
    )

    assert receipt.result_kind == "rendered"
    assert receipt.payload is None
    assert receipt.redirect_route == "/orders"

    replay = _completed_action_response(_request(), receipt, fallback_location="/orders")
    assert replay.status_code == 409
    body = replay.body.decode()
    assert "cannot be replayed" in body
    assert "private fragment" not in body
    assert "must-not-persist" not in body


def test_corrupt_redirect_receipt_fails_closed() -> None:
    receipt = OperationReceipt(
        operation_id="5",
        status="succeeded",
        result_kind="redirect",
        redirect_route="//evil.example",
        payload={"message": "done"},
    )

    replay = _completed_action_response(_request(), receipt, fallback_location="/orders")

    assert replay.status_code == 409
    assert "cannot be replayed" in replay.body.decode()
    assert "location" not in replay.headers


def test_legacy_action_receipt_remains_replayable() -> None:
    receipt = OperationReceipt(
        operation_id="6",
        status="succeeded",
        result_kind="action",
        redirect_route="/orders",
    )

    replay = _completed_action_response(_request(), receipt, fallback_location="/fallback")

    assert replay.status_code == 303
    assert replay.headers["location"] == "/orders"
