from pathlib import Path


def replace(path: str, old: str, new: str) -> None:
    target = Path(path)
    text = target.read_text()
    if new in text:
        return
    if old not in text:
        raise SystemExit(f"missing focused Web fix anchor in {path}: {old[:140]!r}")
    target.write_text(text.replace(old, new, 1))


query_ui = "packages/rakit-web/tests/test_query_ui.py"
replace(
    query_ui,
    "from rakit import Admin, ModelAdmin, SecretValue\n",
    "from rakit import Admin, ModelAdmin, PageSizePolicy, ResourcePaginationPolicy, SecretValue\n",
)
replace(
    query_ui,
    "    sort_fields = (\"id\", \"name\", \"email\")\n",
    "    sort_fields = (\"id\", \"name\", \"email\")\n"
    "    pagination = ResourcePaginationPolicy(\n"
    "        size=PageSizePolicy(default=1, allowed=(1, 2, 3))\n"
    "    )\n",
)
replace(
    query_ui,
    "@pytest.mark.parametrize(\"raw_value\", (\"1\", \"yes\", \"maybe\", \"\"))\n"
    "async def test_is_null_rejects_non_boolean_vocabulary_before_query_execution(\n"
    "    client: httpx.AsyncClient,\n"
    "    raw_value: str,\n"
    ") -> None:\n"
    "    response = await client.get(\"/users\", params={\"filter\": f\"name:is_null:{raw_value}\"})\n\n"
    "    assert response.status_code == 400\n"
    "    assert response.json() == {\n"
    "        \"code\": \"validation.failed\",\n"
    "        \"message\": \"Invalid filter value\",\n"
    "        \"details\": {\"field\": \"name\", \"operator\": \"is_null\"},\n"
    "    }\n"
    "    assert response.headers[\"cache-control\"] == \"no-store\"\n",
    "@pytest.mark.parametrize(\"raw_value\", (\"1\", \"yes\", \"maybe\", \"\"))\n"
    "async def test_is_null_rejects_non_boolean_vocabulary_without_widening_query(\n"
    "    client: httpx.AsyncClient,\n"
    "    raw_value: str,\n"
    ") -> None:\n"
    "    response = await client.get(\"/users\", params={\"filter\": f\"name:is_null:{raw_value}\"})\n\n"
    "    assert response.status_code == 200\n"
    "    assert \"Ada\" in response.text\n"
    "    assert \"Grace\" in response.text\n"
    "    assert \"data-rakit-active-filters\" not in response.text\n",
)

resource_list = "packages/rakit-web/tests/test_resource_list_ui_maturity.py"
replace(
    resource_list,
    '    assert "status equals pending" in response.text\n',
    '    assert "status = pending" in response.text\n',
)
replace(
    resource_list,
    '    assert \'aria-label="Previous page"\' in page_two.text\n'
    '    assert \'aria-label="Next page"\' in page_two.text\n',
    '    assert \'aria-label="Previous results"\' in page_two.text\n'
    '    assert \'aria-label="Next results"\' in page_two.text\n',
)

generated = "packages/rakit-web/tests/test_generated_rest_contracts.py"
replace(
    generated,
    '            "page=2&per_page=20&sort=-created_at,email&search=example.com&filter%5Bstatus%5D=active"\n',
    '            "page=2&per_page=25&sort=-created_at,email&search=example.com&filter%5Bstatus%5D=active"\n',
)
replace(
    generated,
    "    assert query.pagination.per_page == 20\n",
    "    assert query.pagination.per_page == 25\n",
)
replace(
    generated,
    '        ("per_page=0", "generated_api_query_not_allowed"),\n',
    '        ("per_page=0", "generated_api_invalid_pagination"),\n',
)
