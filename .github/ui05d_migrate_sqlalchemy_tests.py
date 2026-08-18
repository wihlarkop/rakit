from pathlib import Path


def replace(path: str, old: str, new: str) -> None:
    target = Path(path)
    text = target.read_text()
    if new in text:
        return
    if old not in text:
        raise SystemExit(f"missing SQLAlchemy migration anchor in {path}: {old[:120]!r}")
    target.write_text(text.replace(old, new, 1))


def replace_all(path: str, old: str, new: str, expected: int) -> None:
    target = Path(path)
    text = target.read_text()
    if new in text and old not in text:
        return
    count = text.count(old)
    if count != expected:
        raise SystemExit(
            f"expected {expected} SQLAlchemy anchors in {path}, found {count}: {old[:120]!r}"
        )
    target.write_text(text.replace(old, new))


datasource = "packages/rakit-sqlalchemy/tests/test_datasource.py"
replace(
    datasource,
    "    NullPlacement,\n    ResourceQuery,\n",
    "    NullPlacement,\n    PageResult,\n    ResourceQuery,\n",
)
replace(
    datasource,
    "    record = await datasource.detail(RecordIdentity(values={\"id\": 1}))\n"
    "    assert [item.name for item in page.items] == [\"Ada\", \"Grace\"]\n",
    "    assert isinstance(page, PageResult)\n"
    "    record = await datasource.detail(RecordIdentity(values={\"id\": 1}))\n"
    "    assert [item.name for item in page.items] == [\"Ada\", \"Grace\"]\n",
)
replace(
    datasource,
    "    )\n"
    "    assert [item.name for item in page.items] == [\"Ada\"]\n"
    "    assert page.total_count == 1\n",
    "    )\n"
    "    assert isinstance(page, PageResult)\n"
    "    assert [item.name for item in page.items] == [\"Ada\"]\n"
    "    assert page.total_count == 1\n",
)
replace(
    datasource,
    "    )\n"
    "    assert [item.name for item in page.items] == [\"Ada\"]\n"
    "    assert page.total_count == 2\n",
    "    )\n"
    "    assert isinstance(page, PageResult)\n"
    "    assert [item.name for item in page.items] == [\"Ada\"]\n"
    "    assert page.total_count == 2\n",
)
replace(
    datasource,
    "    )\n"
    "    assert [item.name for item in second_page.items] == [\"Grace\"]\n",
    "    )\n"
    "    assert isinstance(second_page, PageResult)\n"
    "    assert [item.name for item in second_page.items] == [\"Grace\"]\n",
)

translation = "packages/rakit-sqlalchemy/tests/test_query_translation.py"
replace(
    translation,
    "    OffsetPagination,\n    ResourceQuery,\n",
    "    OffsetPagination,\n    PageResult,\n    ResourceQuery,\n",
)
replace_all(
    translation,
    "    page = await datasource.list(query)\n"
    "    assert len(page.items) == 1\n",
    "    page = await datasource.list(query)\n"
    "    assert isinstance(page, PageResult)\n"
    "    assert len(page.items) == 1\n",
    3,
)
replace(
    translation,
    '    page = await datasource.list(_query(search="work"))\n'
    '    assert [item.name for item in page.items] == ["Grace"]\n',
    '    page = await datasource.list(_query(search="work"))\n'
    "    assert isinstance(page, PageResult)\n"
    '    assert [item.name for item in page.items] == ["Grace"]\n',
)
replace(
    translation,
    '    page = await datasource.list(_query(search="1"))\n'
    "    assert page.items == ()\n",
    '    page = await datasource.list(_query(search="1"))\n'
    "    assert isinstance(page, PageResult)\n"
    "    assert page.items == ()\n",
)
