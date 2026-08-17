from rakit_web.accessibility import describedby_ids, safe_dom_token


def test_safe_dom_token_is_deterministic_and_readable() -> None:
    assert safe_dom_token("orders/line items.email") == "orders-line-items-email"
    assert safe_dom_token("already_safe-1") == "already_safe-1"


def test_describedby_ids_joins_only_present_references() -> None:
    assert describedby_ids("field-help", None, "field-error") == "field-help field-error"
    assert describedby_ids(None, None) is None
