from pathlib import Path


def replace_once(path: str, old: str, new: str) -> None:
    target = Path(path)
    content = target.read_text(encoding="utf-8")
    if content.count(old) != 1:
        raise RuntimeError(f"expected exactly one match in {path}: {old!r}")
    target.write_text(content.replace(old, new, 1), encoding="utf-8")


replace_once(
    "packages/rakit/tests/test_integration_discovery.py",
    '        "persistence.sqlalchemy",\n        "schema.msgspec",',
    '        "persistence.sqlalchemy",\n        "persistence.tortoise",\n        "schema.msgspec",',
)
replace_once(
    "tests/examples/test_read_examples.py",
    '        "rakit_sqlalchemy",\n        "rakit_storage",',
    '        "rakit_sqlalchemy",\n        "rakit_tortoise",\n        "rakit_storage",',
)
replace_once(
    "packages/rakit-tortoise/src/rakit_tortoise/datasource.py",
    "from collections.abc import Iterable\n",
    "",
)
