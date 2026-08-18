from pathlib import Path


def replace_once(path: Path, old: str, new: str) -> None:
    text = path.read_text()
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"expected one match in {path}: {old[:100]!r}; got {count}")
    path.write_text(text.replace(old, new, 1))


main = Path("examples/ui_showcase/main.py")
replace_once(
    main,
    "from .data import CATEGORIES, CUSTOMERS, INVENTORY, ORDERS, PRODUCTS, TEAMS\n",
    "from .advanced_states import ADVANCED_LAUNCHERS, configure_ui06_acceptance\nfrom .data import CATEGORIES, CUSTOMERS, INVENTORY, ORDERS, PRODUCTS, TEAMS\n",
)
replace_once(
    main,
    '''    else:\n        admin.register(resource_admin)\n\n\nasync def pending_orders''',
    '''    else:\n        admin.register(resource_admin)\n\nconfigure_ui06_acceptance(admin)\n\n\nasync def pending_orders''',
)
replace_once(
    main,
    '''            LauncherItem(\n                launcher_id="ui_lab",\n''',
    '''            *ADVANCED_LAUNCHERS,\n            LauncherItem(\n                launcher_id="ui_lab",\n''',
)
print("UI-06 acceptance showcase wired")
