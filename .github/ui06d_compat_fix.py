from pathlib import Path


def replace_once(path: Path, old: str, new: str) -> None:
    text = path.read_text()
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"expected one match in {path}: {old[:100]!r}; got {count}")
    path.write_text(text.replace(old, new, 1))


routes = Path("packages/rakit-web/src/rakit_web/page_routes.py")
replace_once(
    routes,
    '''            "description": field.description,\n            "description_id": f"rakit-page-{field.name}-description",\n            "error_id": f"rakit-page-{field.name}-error",\n            "value": submitted.get(field.name, ""),\n''',
    '''            "description": field.description,\n            "value": submitted.get(field.name, ""),\n''',
)

page = Path("packages/rakit-web/src/rakit_web/templates/pages/page.html")
replace_once(
    page,
    '''          {% set described = [] %}\n          {% if field.description %}{% set _ = described.append(field.description_id) %}{% endif %}\n          {% if field.issues %}{% set _ = described.append(field.error_id) %}{% endif %}\n''',
    '''          {% set description_id = field.id ~ '-description' %}\n          {% set error_id = field.id ~ '-error' %}\n          {% set described = [] %}\n          {% if field.description %}{% set _ = described.append(description_id) %}{% endif %}\n          {% if field.issues %}{% set _ = described.append(error_id) %}{% endif %}\n''',
)
replace_once(page, 'id="{{ field.description_id }}"', 'id="{{ description_id }}"')
replace_once(page, 'id="{{ field.error_id }}"', 'id="{{ error_id }}"')

tests = Path("packages/rakit-web/tests/test_custom_page_ui_maturity.py")
replace_once(tests, '        page_id="unsafe-payload",\n', '        page_id="unsafe_payload",\n')
replace_once(
    tests,
    '''            "description": "Why this operation is needed",\n            "description_id": "rakit-page-reason-description",\n            "error_id": "rakit-page-reason-error",\n            "value": "x",\n''',
    '''            "description": "Why this operation is needed",\n            "value": "x",\n''',
)
replace_once(
    tests,
    '''    assert "action_group(page_actions" in page_template\n    assert "aria-describedby=\\\"{{ described | join(' ') }}\\\"" in page_template\n''',
    '''    assert "action_group(page_actions" in page_template\n    assert "{% set description_id = field.id ~ '-description' %}" in page_template\n    assert "{% set error_id = field.id ~ '-error' %}" in page_template\n    assert "aria-describedby=\\\"{{ described | join(' ') }}\\\"" in page_template\n''',
)

print("UI-06D compatibility fix applied")
