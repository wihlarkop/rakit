from pathlib import Path


path = Path("packages/rakit-web/src/rakit_web/admin.py")
text = path.read_text()
old = '''                for name in (
                    "create",
                    "get",
                    "issue_update_token",
                    "update",
                    "issue_delete_token",
                    "delete",
                )
'''
new = '''                for name in (
                    "create",
                    "get",
                    "issue_update_token",
                    "update",
                    "issue_delete_token",
                    "delete",
                    "bind_delete_nonce_store",
                )
'''
if new in text:
    print("provider hardening already applied")
elif text.count(old) == 1:
    path.write_text(text.replace(old, new, 1))
else:
    raise SystemExit(f"expected one provider contract block, got {text.count(old)}")
