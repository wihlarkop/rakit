from pathlib import Path


def replace_once(path: Path, old: str, new: str) -> None:
    text = path.read_text()
    if old not in text:
        raise RuntimeError(f"missing patch anchor in {path}: {old[:100]!r}")
    path.write_text(text.replace(old, new, 1))


read_examples = Path("tests/examples/test_read_examples.py")
replace_once(
    read_examples,
    '''        sort_href_match = re.search(r'<th[^>]*>\\s*<a href="([^\"]+)"', full.text)
        assert sort_href_match is not None
        sort_href = html.unescape(sort_href_match.group(1))
        sort_response = await client.get(sort_href)
''',
    '''        sort_button_match = re.search(
            r'<button[^>]+name="sort"[^>]+value="([^\"]+)"', full.text
        )
        assert sort_button_match is not None
        sort_value = html.unescape(sort_button_match.group(1))
        sort_href = f"/admin/users?{urlencode({'sort': sort_value})}"
        sort_response = await client.get(sort_href)
''',
)

dashboard = Path("packages/rakit-web/tests/test_dashboard_runtime.py")
replace_once(
    dashboard,
    '''    assert 'class="hidden text-xs text-slate-500 [.htmx-request&]:inline"' in response.text
''',
    '''    assert "hidden text-xs text-slate-500" in response.text
    assert "[.htmx-request&]:inline" in response.text
''',
)

query = Path("packages/rakit-web/tests/test_query_ui.py")
replace_once(
    query,
    '''async def test_sort_header_link_omits_page(client: httpx.AsyncClient) -> None:
    response = await client.get("/users", params={"page": "1", "sort": "name"})
    # Sort-toggle links reset pagination: they never carry a page param forward.
    assert "sort=-name" in response.text
    hrefs = [html.unescape(value) for value in re.findall(r'href="([^\"]+)"', response.text)]
    assert all(
        not any(key == "page" for key, _value in parse_qsl(urlsplit(href).query)) for href in hrefs
    )
''',
    '''async def test_sort_header_control_omits_page(client: httpx.AsyncClient) -> None:
    response = await client.get("/users", params={"page": "1", "sort": "name"})
    sort_url, sort_pairs = _sort_link(response.text, "name")

    assert ("sort", "-name") in sort_pairs
    assert not any(key == "page" for key, _value in sort_pairs)
    assert not any(
        key == "page" for key, _value in parse_qsl(urlsplit(sort_url).query)
    )
''',
)
replace_once(
    query,
    '''    assert re.search(r'aria-sort="descending"[^>]*>\\s*<a[^>]*>name</a>', response.text)
    assert re.search(r'aria-sort="other"[^>]*>\\s*<a[^>]*>email</a>', response.text)
    assert re.search(r'aria-sort="none"[^>]*>\\s*<a[^>]*>id</a>', response.text)
''',
    '''    assert re.search(
        r'aria-sort="descending"[^>]*>\\s*<button[^>]*>\\s*name\\s*</button>', response.text
    )
    assert re.search(
        r'aria-sort="other"[^>]*>\\s*<button[^>]*>\\s*email\\s*</button>', response.text
    )
    assert re.search(
        r'aria-sort="none"[^>]*>\\s*<button[^>]*>\\s*id\\s*</button>', response.text
    )
''',
)

write_forms = Path("packages/rakit-web/tests/test_write_forms.py")
replace_once(
    write_forms,
    '''    assert 'id="contact-details" open' in response.text
''',
    '''    contact_details = response.text.split('id="contact-details"', 1)[1].split(">", 1)[0]
    assert " open" in contact_details
''',
)
