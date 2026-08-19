from pathlib import Path

path = Path("packages/rakit-web/src/rakit_web/bulk_admin.py")
text = path.read_text()
old = "    write_resource_bindings: Mapping[str, WriteResourceBinding],\n"
new = "    write_resource_bindings: Mapping[str, WriteResourceBinding] | None = None,\n"
if text.count(old) != 1:
    raise RuntimeError("bulk_admin.py: write_resource_bindings signature drifted")
text = text.replace(old, new, 1)
old = "    routes: list[Route] = []\n\n    def bulk_action_views"
new = "    routes: list[Route] = []\n    write_bindings = write_resource_bindings or {}\n\n    def bulk_action_views"
if text.count(old) != 1:
    raise RuntimeError("bulk_admin.py: routes initialization drifted")
text = text.replace(old, new, 1)
if text.count("write_resource_bindings.get(resource_id)") != 1:
    raise RuntimeError("bulk_admin.py: expected one launcher lookup")
text = text.replace("write_resource_bindings.get(resource_id)", "write_bindings.get(resource_id)")
if text.count("write_resource_bindings.items()") != 1:
    raise RuntimeError("bulk_admin.py: expected one built-in route loop")
text = text.replace("write_resource_bindings.items()", "write_bindings.items()")
path.write_text(text)
print("UI-06 bulk-admin compatibility patch applied")
