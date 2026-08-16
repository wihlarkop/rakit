from pathlib import Path


REPLACEMENTS: dict[str, list[tuple[str, str]]] = {
    "packages/rakit-auth-sqlalchemy/src/rakit_auth_sqlalchemy/models.py": [
        (
            "    (Task 5) from compiled resources/pages/actions/endpoints. `orphaned`\n",
            "    from compiled resources/pages/actions/endpoints. `orphaned`\n",
        ),
    ],
    "packages/rakit-core/src/rakit_core/endpoints.py": [
        (
            "Task 7 keeps endpoint declarations and execution semantic: core knows about\n",
            "Endpoint declarations and execution remain semantic: core knows about\n",
        ),
        (
            "returned. Task 7 restricts streaming endpoints to read-only GET operations,\n",
            "returned. Streaming endpoints are restricted to read-only GET operations,\n",
        ),
        (
            "    mutation endpoints are intentionally deferred in Task 7 because anonymous\n",
            "    public mutation endpoints are intentionally unsupported because anonymous\n",
        ),
        (
            'raise ValueError("Public POST endpoints are not supported in Task 7")',
            'raise ValueError("Public POST endpoints are not supported")',
        ),
        (
            'raise ValueError("Task 7 POST endpoints must return JSON")',
            'raise ValueError("POST endpoints must return JSON")',
        ),
    ],
    "packages/rakit-core/src/rakit_core/actions.py": [
        (
            '"(Task 5 owns bulk concurrency snapshots)"',
            '"(bulk actions own their own concurrency snapshots)"',
        ),
    ],
    "packages/rakit-sqlalchemy/src/rakit_sqlalchemy/action_mutations.py": [
        (
            '"""Sanctioned SQLAlchemy mutation executors for Task 4 Correction C2B.\n',
            '"""Sanctioned SQLAlchemy mutation executors for action operations.\n',
        ),
    ],
    "packages/rakit-web/src/rakit_web/bulk_runtime.py": [
        (
            '"""Compatibility imports for the canonical Task 5 bulk route runtime."""',
            '"""Compatibility imports for the canonical bulk route runtime."""',
        ),
    ],
    "packages/rakit-web/src/rakit_web/endpoint_admin.py": [
        (
            '"""Fail closed for endpoint combinations Task 7 cannot safely guarantee."""',
            '"""Fail closed for endpoint combinations the runtime cannot safely guarantee."""',
        ),
        (
            '"Task 7 endpoint runtime supports static paths only."',
            '"Custom endpoint runtime supports static paths only."',
        ),
        (
            'message="Task 7 endpoints must declare exactly one HTTP method."',
            'message="Custom endpoints must declare exactly one HTTP method."',
        ),
        (
            'message="Task 7 GET endpoints accept QUERY input only."',
            'message="GET endpoints accept QUERY input only."',
        ),
        (
            'message="Public POST endpoints are intentionally deferred beyond Task 7."',
            'message="Public POST endpoints are not supported by the current runtime."',
        ),
        (
            'message="Task 7 POST endpoints accept JSON or FORM input only."',
            'message="POST endpoints accept JSON or FORM input only."',
        ),
        (
            'message="Task 7 POST endpoint responses must be replayable JSON."',
            'message="POST endpoint responses must be replayable JSON."',
        ),
        (
            'message="Advanced raw response adapters are deferred beyond Task 7."',
            'message="Advanced raw response adapters are not supported."',
        ),
        (
            "    The base Starlette admin remains unchanged; Task 7 adds an exact-path API\n",
            "    The base Starlette admin remains unchanged; custom endpoints add an exact-path API\n",
        ),
    ],
    "packages/rakit-web/src/rakit_web/page_admin.py": [
        (
            "                    f'Page \"{page.page_id}\" uses a parameterized path, but Task 6 '\n",
            "                    f'Page \"{page.page_id}\" uses a parameterized path, but the '\n",
        ),
    ],
}


for filename, replacements in REPLACEMENTS.items():
    path = Path(filename)
    text = path.read_text(encoding="utf-8")
    for old, new in replacements:
        if old not in text:
            raise SystemExit(f"expected marker not found in {filename}: {old!r}")
        text = text.replace(old, new, 1)
    path.write_text(text, encoding="utf-8")
