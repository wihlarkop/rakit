from pathlib import Path

# This helper intentionally does only local source cleanup after the branch has
# been merged with the latest integration head by the workflow.
test_path = Path("packages/rakit-web/tests/test_ui06_showcase_acceptance.py")
if not test_path.exists():
    raise RuntimeError("UI-06 acceptance regression test is missing")

advanced = Path("examples/ui_showcase/advanced_states.py")
if not advanced.exists():
    raise RuntimeError("UI-06 advanced showcase fixture is missing")

main = Path("examples/ui_showcase/main.py").read_text()
for marker in (
    "ADVANCED_LAUNCHERS",
    "advanced_states",
):
    if marker not in main:
        raise RuntimeError(f"showcase main lost acceptance marker {marker!r}")

print("UI-06 acceptance fixtures present after integration refresh")
