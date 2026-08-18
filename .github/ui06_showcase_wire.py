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

advanced = Path("examples/ui_showcase/advanced_states.py")
replace_once(advanced, "    TransactionPolicy,\n", "")
replace_once(
    advanced,
    "from rakit_core.resources import ResourceService\n",
    "from rakit_core.resources import ResourceService\nfrom rakit_core.transactions import TransactionPolicy\n",
)
replace_once(
    advanced,
    '        description="Writable TO_ONE/TO_MANY, pagination, inline reorder, and unlink-only UI-06B states.",\n',
    '''        description=(\n            "Writable TO_ONE/TO_MANY, pagination, inline reorder, "\n            "and unlink-only UI-06B states."\n        ),\n''',
)
replace_once(
    advanced,
    '        description="Create and edit FileField flows with a real in-memory development storage descriptor.",\n',
    '''        description=(\n            "Create and edit FileField flows with a real in-memory development "\n            "storage descriptor."\n        ),\n''',
)
replace_once(
    advanced,
    '                    description="Replace the current PDF or leave it empty to keep the existing file.",\n',
    '''                    description=(\n                        "Replace the current PDF or leave it empty to keep the existing file."\n                    ),\n''',
)
print("UI-06 acceptance showcase wired")
