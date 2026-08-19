from pathlib import Path


def replace_once(path: str, old: str, new: str) -> None:
    file = Path(path)
    text = file.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"expected exactly one match in {path}, got {count}: {old!r}")
    file.write_text(text.replace(old, new, 1), encoding="utf-8")


replace_once(
    "tests/test_ui_showcase.py",
    '    assert "This change is applied only when you confirm and submit." in refund.text\n',
    '    assert "marked as potentially destructive" in refund.text\n'
    '    assert "runs only when you confirm and submit" in refund.text\n',
)

replace_once(
    "packages/rakit-web/tests/test_resource_detail_form_ui_maturity.py",
    '    assert "physical or recoverable deletion" in response.text\n'
    '    assert "cannot be undone" not in response.text.casefold()\n'
    '    assert "permanent" not in response.text.casefold()\n',
    '    assert "permanent or recoverable" in response.text\n'
    '    assert "Confirm only if you intend to remove this record." in response.text\n'
    '    assert "cannot be undone" not in response.text.casefold()\n',
)
