from pathlib import Path


def replace_once(path: Path, old: str, new: str) -> None:
    text = path.read_text()
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"expected one match in {path}: {old[:100]!r}; got {count}")
    path.write_text(text.replace(old, new, 1))


page_routes = Path("packages/rakit-web/src/rakit_web/page_routes.py")
replace_once(page_routes, "from html import escape\n", "")
replace_once(
    page_routes,
    "from starlette.responses import HTMLResponse, RedirectResponse, Response\n",
    "from starlette.responses import RedirectResponse, Response\n",
)
replace_once(
    page_routes,
    "from ._paths import mounted_path\n",
    "from ._paths import mounted_path\nfrom .page_payload import page_payload_view\n",
)
replace_once(
    page_routes,
    '''            "description": field.description,\n            "value": submitted.get(field.name, ""),\n            "issues": issues.get(field.name, ()),\n''',
    '''            "description": field.description,\n            "description_id": f"rakit-page-{field.name}-description",\n            "error_id": f"rakit-page-{field.name}-error",\n            "value": submitted.get(field.name, ""),\n            "issues": issues.get(field.name, ()),\n''',
)
replace_once(
    page_routes,
    '''        "page": page,\n        "payload": result.payload if result is not None else None,\n        "message": message\n''',
    '''        "page": page,\n        "payload": result.payload if result is not None else None,\n        "payload_view": page_payload_view(result.payload if result is not None else None),\n        "dashboard_url": mounted_path(request, "/"),\n        "message": message\n''',
)
old_rejected = '''def _rejected_response(message: str, status_code: int) -> Response:\n    safe = escape(message, quote=True)\n    return HTMLResponse(\n        "<main class='mx-auto w-full max-w-7xl px-4 py-6 sm:px-6 lg:px-8'>"\n        f"<section class='rakit-panel p-4'><p class='text-sm text-red-900'>{safe}</p>"\n        "</section></main>",\n        status_code=status_code,\n        headers={"Cache-Control": "no-store"},\n    )\n'''
new_rejected = '''def _rejected_response(\n    binding: PageBinding, request: Request, message: str, status_code: int\n) -> Response:\n    return binding.templates.TemplateResponse(\n        request,\n        "pages/rejected.html",\n        {\n            "binding_label": binding.label,\n            "dashboard_url": mounted_path(request, "/"),\n            "rejection_message": message,\n        },\n        status_code=status_code,\n        headers={"Cache-Control": "no-store"},\n    )\n'''
replace_once(page_routes, old_rejected, new_rejected)
replace_once(
    page_routes,
    "def _completed_response(request: Request, receipt: OperationReceipt | None) -> Response:\n",
    "def _completed_response(\n    binding: PageBinding, request: Request, receipt: OperationReceipt | None\n) -> Response:\n",
)
# All rejection calls occur inside scopes that now have binding + request.
text = page_routes.read_text()
return_count = text.count("return _rejected_response(")
if return_count != 10:
    raise RuntimeError(f"expected 10 rejection return sites, got {return_count}")
text = text.replace("return _rejected_response(", "return _rejected_response(binding, request, ")
if text.count("return _completed_response(request, reservation.completed_receipt)") != 1:
    raise RuntimeError("expected one completed replay call")
text = text.replace(
    "return _completed_response(request, reservation.completed_receipt)",
    "return _completed_response(binding, request, reservation.completed_receipt)",
)
page_routes.write_text(text)

print("UI-06D page runtime presentation wiring applied")
