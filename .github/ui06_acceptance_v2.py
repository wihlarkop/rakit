from pathlib import Path

main_path = Path("examples/ui_showcase/main.py")
main = main_path.read_text()

replacements = (
    (
        "from rakit_core.forms import FormSchema\n\nfrom .data import CATEGORIES, CUSTOMERS, INVENTORY, ORDERS, PRODUCTS, TEAMS\n",
        "from rakit_core.forms import FormSchema\n\nfrom .advanced_states import ADVANCED_LAUNCHERS, configure_ui06_acceptance\nfrom .data import CATEGORIES, CUSTOMERS, INVENTORY, ORDERS, PRODUCTS, TEAMS\n",
    ),
    (
        "    else:\n        admin.register(resource_admin)\n\n\nasync def pending_orders",
        "    else:\n        admin.register(resource_admin)\n\nconfigure_ui06_acceptance(admin)\n\n\nasync def pending_orders",
    ),
    (
        "                description=\"Exercise page action hierarchy, disabled state, and hidden state.\",\n            ),\n            LauncherItem(\n                launcher_id=\"ui_lab\"",
        "                description=\"Exercise page action hierarchy, disabled state, and hidden state.\",\n            ),\n            *ADVANCED_LAUNCHERS,\n            LauncherItem(\n                launcher_id=\"ui_lab\"",
    ),
)

for old, new in replacements:
    count = main.count(old)
    if count != 1:
        raise RuntimeError(f"main.py acceptance insertion drifted; expected 1 match, found {count}")
    main = main.replace(old, new, 1)

main_path.write_text(main)
print("Applied UI-06 acceptance main.py insertions")
