from pathlib import Path


def replace_once(path: Path, old: str, new: str) -> None:
    text = path.read_text()
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{path}: expected one replacement, found {count}: {old[:90]!r}")
    path.write_text(text.replace(old, new, 1))


main_path = Path("examples/ui_showcase/main.py")
main = main_path.read_text()

main_replacements = (
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

for old, new in main_replacements:
    count = main.count(old)
    if count != 1:
        raise RuntimeError(f"main.py acceptance insertion drifted; expected 1 match, found {count}")
    main = main.replace(old, new, 1)
main_path.write_text(main)

advanced = Path("examples/ui_showcase/advanced_states.py")
replace_once(
    advanced,
    "from typing import Any, cast\n",
    "from typing import Any, cast\nfrom uuid import UUID\n",
)
replace_once(
    advanced,
    "from rakit_core.identity import RecordIdentity\nfrom rakit_core.mutations import MutationAuthorization, OperationAuthorizationSet\n",
    "from rakit_core.idempotency import IdempotencyReservation, IdempotencyStatus, OperationReceipt\nfrom rakit_core.identity import RecordIdentity\nfrom rakit_core.mutations import MutationAuthorization, MutationOperation, OperationAuthorizationSet\n",
)
replace_once(
    advanced,
    "from rakit_storage import FileAccess, FileStorage, StoredFile, TemporaryUpload\n",
    "from rakit_storage import FileAccess, FileStorage, StoredFile, TemporaryUpload\nfrom starlette.requests import Request\n",
)
replace_once(
    advanced,
    '''    async def begin(self, token_hash: str, *, fingerprint: str) -> object:
        from rakit_core.mutations import IdempotencyReservation, IdempotencyStatus

        del token_hash, fingerprint
        return IdempotencyReservation(1, IdempotencyStatus.IN_PROGRESS)

    async def complete(self, reservation: object, receipt: object) -> None:
        del reservation, receipt

    async def release(self, reservation: object) -> None:
        del reservation

    async def fail_final(self, reservation: object) -> None:
        del reservation
''',
    '''    async def begin(self, token_hash: str, *, fingerprint: str) -> IdempotencyReservation:
        del token_hash, fingerprint
        return IdempotencyReservation(1, IdempotencyStatus.IN_PROGRESS)

    async def complete(
        self, reservation: IdempotencyReservation, receipt: OperationReceipt
    ) -> None:
        del reservation, receipt

    async def release(self, reservation: IdempotencyReservation) -> None:
        del reservation

    async def fail_final(self, reservation: IdempotencyReservation) -> None:
        del reservation
''',
)
replace_once(
    advanced,
    '''    def __init__(self, rows: tuple[dict[str, object], ...], fields: tuple[str, ...]) -> None:
        self.rows = rows
        self.fields = fields
        self.identity_fields = ("id",)

    def identity_for(self, record: Mapping[str, object]) -> RecordIdentity:
        return RecordIdentity(values={"id": record["id"]})
''',
    '''    def __init__(self, rows: tuple[Mapping[str, object], ...], fields: tuple[str, ...]) -> None:
        self.rows: tuple[dict[str, object], ...] = tuple(dict(row) for row in rows)
        self.fields = fields
        self.identity_fields = ("id",)

    def identity_for(self, record: Mapping[str, object]) -> RecordIdentity:
        value = record["id"]
        if not isinstance(value, str | int | UUID) or isinstance(value, bool):
            raise TypeError("showcase record id must be an identity scalar")
        return RecordIdentity(values={"id": value})
''',
)
replace_once(
    advanced,
    '''    def __init__(self) -> None:
        self._records = {int(row["id"]): dict(row) for row in RELATIONSHIP_RECORDS}

    async def get(self, identity: RecordIdentity) -> dict[str, object] | None:
        return self._records.get(int(identity.values["id"]))
''',
    '''    def __init__(self) -> None:
        self._records: dict[int, dict[str, object]] = {
            int(row["id"]): {key: value for key, value in row.items()}
            for row in RELATIONSHIP_RECORDS
        }

    async def get(self, identity: RecordIdentity) -> dict[str, object] | None:
        return self._records.get(int(identity.values["id"]))
''',
)
replace_once(
    advanced,
    '''async def _mutation_authorization(
    _request: object, operation: object, identity: RecordIdentity | None
) -> MutationAuthorization:
''',
    '''async def _mutation_authorization(
    _request: object, operation: MutationOperation, identity: RecordIdentity | None
) -> MutationAuthorization:
''',
)
replace_once(
    advanced,
    '''async def _editor_authorization(
    _request: object, _relationship_id: str, _parent_identity: RecordIdentity
) -> bool:
''',
    '''async def _editor_authorization(
    _request: Request,
    _relationship_id: str,
    _parent_identity: RecordIdentity | None,
    /,
) -> bool:
''',
)

test_path = Path("packages/rakit-web/tests/test_ui06_showcase_acceptance.py")
replace_once(
    test_path,
    '''    compiled_page_ids = {str(page.page_id) for page in admin.compiled.compiled_pages}
''',
    '''    compiled = admin.compiled
    assert compiled is not None
    compiled_page_ids = {str(page.definition.page_id) for page in compiled.compiled_pages}
''',
)

print("Applied UI-06 acceptance wiring and protocol typing fixes")
