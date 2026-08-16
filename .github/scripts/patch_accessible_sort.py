from pathlib import Path

ROUTES = Path("packages/rakit-web/src/rakit_web/resource_routes.py")
TESTS = Path("packages/rakit-web/tests/test_query_ui.py")


def replace_once(text: str, old: str, new: str) -> str:
    if old not in text:
        raise RuntimeError(f"missing patch anchor: {old[:120]!r}")
    return text.replace(old, new, 1)


text = ROUTES.read_text()
text = replace_once(
    text,
    '            headers.append({"field": field_name, "url": "", "aria_sort": "none"})',
    '            headers.append(\n                {"field": field_name, "url": "", "sort_value": "", "aria_sort": "none"}\n            )',
)
text = replace_once(
    text,
    '''                "field": field_name,
                "url": f"{path}?{urlencode(params)}",
                "aria_sort": aria_sort,
''',
    '''                "field": field_name,
                "url": f"{path}?{urlencode(params)}",
                "sort_value": next_sort,
                "aria_sort": aria_sort,
''',
)
ROUTES.write_text(text)

text = TESTS.read_text()
text = replace_once(
    text,
    "from urllib.parse import parse_qsl, urlsplit\n",
    "from urllib.parse import parse_qsl, urlencode, urlsplit\n",
)
start = text.index("def _sort_link(document: str, field: str)")
end = text.index("\n\ndef _search_form", start)
replacement = '''def _sort_link(document: str, field: str) -> tuple[str, list[tuple[str, str]]]:
    form_match = re.search(
        r'<form id="(rakit-sort-[^"]+)" method="get" action="([^"]+)" class="hidden" aria-hidden="true">(.*?)</form>',
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
text = text[:start] + replacement + text[end:]

start = text.index("def _search_form(document: str)")
end = text.index("\n\ndef _table_cell_texts", start)
replacement = '''def _search_form(document: str) -> tuple[str, list[tuple[str, str]]]:
    form_match = re.search(
        r'<form[^>]+data-rakit-search[^>]+action="([^"]+)"[^>]*>(.*?)</form>',
        document,
        flags=re.DOTALL,
    )
    assert form_match is not None
    action, body = form_match.groups()
    hidden = re.findall(
        r'<input\\s+type="hidden"\\s+name="([^"]+)"\\s+value="([^"]*)"\\s*/?>',
        body,
    )
    return html.unescape(action), [
        (html.unescape(name), html.unescape(value)) for name, value in hidden
    ]
'''
text = text[:start] + replacement + text[end:]
TESTS.write_text(text)
