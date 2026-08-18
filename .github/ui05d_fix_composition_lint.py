from pathlib import Path

admin = Path("packages/rakit-web/src/rakit_web/admin.py")
text = admin.read_text()
old = 'if not isinstance(raw_filters, (list, tuple)) or not all('
if old not in text:
    raise SystemExit("admin isinstance normalization anchor missing")
admin.write_text(text.replace(old, 'if not isinstance(raw_filters, list | tuple) or not all(', 1))

compiler = Path("packages/rakit-core/src/rakit_core/compiler.py")
text = compiler.read_text()
old = '                message=f\'Resource "{definition.resource_id}" requests an unsupported pagination strategy.\',\n'
new = (
    '                message=(\n'
    '                    f\'Resource "{definition.resource_id}" requests an unsupported \'\n'
    '                    "pagination strategy."\n'
    '                ),\n'
)
if old not in text:
    raise SystemExit("compiler message normalization anchor missing")
compiler.write_text(text.replace(old, new, 1))
