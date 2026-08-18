from pathlib import Path
import re

path = Path("packages/rakit-web/src/rakit_web/form_routes.py")
text = path.read_text()
start_marker = "    controls: dict[str, dict[str, object]] = {}\n"
end_marker = "    relationship_panels = await render_relationship_panels(\n"
start = text.index(start_marker)
end = text.index(end_marker, start)
block = text[start:end]
if block.count("for field in binding.form_schema.fields:") != 1:
    raise RuntimeError("expected one control loop")
block = re.sub(r"\bfield\b", "schema_field", block)
text = text[:start] + block + text[end:]
path.write_text(text)
print("renamed UI-06B control loop variable")
