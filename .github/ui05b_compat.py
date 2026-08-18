from pathlib import Path


def replace_once(text: str, old: str, new: str, *, label: str) -> str:
    if old not in text:
        raise SystemExit(f"{label} not found")
    return text.replace(old, new, 1)


count = Path("packages/rakit-web/src/rakit_web/templates/resources/_count.html")
count.write_text("{{ total }}\n", encoding="utf-8")

table = Path("packages/rakit-web/src/rakit_web/templates/resources/_table.html")
text = table.read_text(encoding="utf-8")
text = replace_once(
    text,
    '      <span data-rakit-total-deferred hx-get="{{ count_url }}" hx-trigger="load" hx-swap="outerHTML">Calculating total…</span>',
    '      <span data-rakit-total-deferred><span hx-get="{{ count_url }}" hx-trigger="load" hx-swap="innerHTML">Calculating</span> total</span>',
    label="deferred count placeholder",
)
text = replace_once(
    text,
    '                aria-label="Change sort for {{ header.field }}"',
    '                aria-label="Sort by {{ header.field }}"',
    label="sort aria-label",
)
table.write_text(text, encoding="utf-8")

examples = Path("tests/examples/test_read_examples.py")
text = examples.read_text(encoding="utf-8")
if text.count('assert "Total unknown" in fragment.text') != 2:
    raise SystemExit("unexpected Total unknown assertion count")
text = text.replace(
    'assert "Total unknown" in fragment.text',
    'assert "Total unavailable" in fragment.text',
)
if text.count('assert "Calculating total" in deferred.text') != 2:
    raise SystemExit("unexpected example deferred-count assertion count")
text = text.replace(
    'assert "Calculating total" in deferred.text',
    'assert "data-rakit-total-deferred" in deferred.text\n    assert "Calculating" in deferred.text',
)
examples.write_text(text, encoding="utf-8")

showcase = Path("tests/test_ui_showcase.py")
text = showcase.read_text(encoding="utf-8")
text = replace_once(
    text,
    '    assert "Page 2" in orders_page_two.text\n',
    '    assert \'aria-current="page">2</a>\' in orders_page_two.text\n',
    label="showcase current-page assertion",
)
showcase.write_text(text, encoding="utf-8")

query_tests = Path("packages/rakit-web/tests/test_query_ui.py")
text = query_tests.read_text(encoding="utf-8")
old_sort_helper = '''def _sort_link(document: str, field: str) -> tuple[str, list[tuple[str, str]]]:
    form_match = re.search(
        (
            r'<form id="(rakit-sort-[^"]+)" method="get" action="([^"]+)" '
            r'class="hidden" aria-hidden="true">(.*?)</form>'
        ),
        document,
        flags=re.DOTALL,
    )
    assert form_match is not None
    form_id, action, body = form_match.groups()
    button = re.search(
        rf'<button\\s+type="submit"\\s+form="{re.escape(form_id)}"\\s+name="sort"\\s+value="([^"]+)"[^>]*>\\s*{re.escape(field)}\\s*</button>',
        document,
        flags=re.DOTALL,
    )
    assert button is not None
    hidden = re.findall(
        r'<input\\s+type="hidden"\\s+name="([^"]+)"\\s+value="([^"]*)"\\s*/?>',
        body,
    )
    pairs = [(html.unescape(name), html.unescape(value)) for name, value in hidden]
    pairs.append(("sort", html.unescape(button.group(1))))
    url = f"{html.unescape(action)}?{urlencode(pairs)}"
    return url, pairs
'''
new_sort_helper = '''def _sort_link(document: str, field: str) -> tuple[str, list[tuple[str, str]]]:
    form_match = re.search(
        (
            r'<form id="(rakit-sort-[^"]+)" method="get" action="([^"]+)" '
            r'class="hidden" aria-hidden="true">(.*?)</form>'
        ),
        document,
        flags=re.DOTALL,
    )
    assert form_match is not None
    form_id, action, body = form_match.groups()
    buttons = re.finditer(
        rf'<button\\s+type="submit"\\s+form="{re.escape(form_id)}"\\s+name="sort"\\s+value="([^"]+)"[^>]*>(.*?)</button>',
        document,
        flags=re.DOTALL,
    )
    button_value: str | None = None
    for button in buttons:
        candidate_value, candidate_body = button.groups()
        candidate_text = html.unescape(re.sub(r"<[^>]+>", "", candidate_body)).strip()
        if candidate_text == field:
            button_value = candidate_value
            break
    assert button_value is not None
    hidden = re.findall(
        r'<input\\s+type="hidden"\\s+name="([^"]+)"\\s+value="([^"]*)"\\s*/?>',
        body,
    )
    pairs = [(html.unescape(name), html.unescape(value)) for name, value in hidden]
    pairs.append(("sort", html.unescape(button_value)))
    url = f"{html.unescape(action)}?{urlencode(pairs)}"
    return url, pairs
'''
text = replace_once(text, old_sort_helper, new_sort_helper, label="sort helper")

pagination_helper = '''def _pagination_link(document: str, label: str) -> tuple[str, list[tuple[str, str]]] | None:
    match = re.search(rf'<a[^>]+aria-label="{re.escape(label)}"[^>]+href="([^"]+)"', document)
    if match is None:
        return None
    url = html.unescape(match.group(1))
    return url, parse_qsl(urlsplit(url).query, keep_blank_values=True)
'''
semantic_helpers = pagination_helper + '''\n\ndef _has_pagination_landmark(document: str) -> bool:
    return re.search(r'<nav[^>]+aria-label="Resource pagination"', document) is not None


def _has_current_page(document: str, page: int) -> bool:
    return (
        re.search(
            rf'aria-current="page"[^>]*>\\s*{page}\\s*</(?:a|span)>',
            document,
        )
        is not None
    )


def _sorted_header_has_field(document: str, *, aria_sort: str, field: str) -> bool:
    match = re.search(
        rf'<th[^>]*aria-sort="{re.escape(aria_sort)}"[^>]*>(.*?)</th>',
        document,
        flags=re.DOTALL,
    )
    if match is None:
        return False
    text_content = html.unescape(re.sub(r"<[^>]+>", "", match.group(1)))
    return field in text_content.split()
'''
text = replace_once(
    text,
    pagination_helper,
    semantic_helpers,
    label="pagination helper",
)

for old, new in (
    ('    assert \'nav aria-label="Resource pagination"\' in first.text\n', '    assert _has_pagination_landmark(first.text)\n'),
    ('    assert ">Page 1<" in first.text\n', '    assert _has_current_page(first.text, 1)\n'),
    ('    assert ">Page 2<" in middle.text\n', '    assert _has_current_page(middle.text, 2)\n'),
    ('    assert ">Page 3<" in last.text\n', '    assert _has_current_page(last.text, 3)\n'),
    ('    assert "Calculating total" in page.text\n', '    assert "data-rakit-total-deferred" in page.text\n    assert "Calculating" in page.text\n'),
):
    text = replace_once(text, old, new, label=f"semantic assertion {old!r}")

old_sort_assertions = '''    assert re.search(
        r'aria-sort="descending"[^>]*>\\s*<button[^>]*>\\s*name\\s*</button>', response.text
    )
    assert re.search(r'aria-sort="other"[^>]*>\\s*<button[^>]*>\\s*email\\s*</button>', response.text)
    assert re.search(r'aria-sort="none"[^>]*>\\s*<button[^>]*>\\s*id\\s*</button>', response.text)
'''
new_sort_assertions = '''    assert _sorted_header_has_field(response.text, aria_sort="descending", field="name")
    assert _sorted_header_has_field(response.text, aria_sort="other", field="email")
    assert _sorted_header_has_field(response.text, aria_sort="none", field="id")
'''
text = replace_once(
    text,
    old_sort_assertions,
    new_sort_assertions,
    label="aria-sort assertions",
)
query_tests.write_text(text, encoding="utf-8")

resource_maturity = Path("packages/rakit-web/tests/test_resource_list_ui_maturity.py")
text = resource_maturity.read_text(encoding="utf-8")
text = replace_once(
    text,
    '    assert "Calculating total…" in deferred.text\n',
    '    assert "data-rakit-total-deferred" in deferred.text\n    assert "Calculating" in deferred.text\n',
    label="resource maturity deferred-count assertion",
)
resource_maturity.write_text(text, encoding="utf-8")
