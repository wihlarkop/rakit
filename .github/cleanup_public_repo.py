from __future__ import annotations

from pathlib import Path
import shutil


RENAMES = {
    "packages/rakit-core/tests/test_plan05_foundations.py":
        "packages/rakit-core/tests/test_operation_and_composition_foundations.py",
    "packages/rakit-core/tests/test_plan05_task4_correction_a.py":
        "packages/rakit-core/tests/test_action_definition_contract.py",
    "packages/rakit-core/tests/test_plan05_task4_correction_b1.py":
        "packages/rakit-core/tests/test_action_route_compilation.py",
    "packages/rakit-core/tests/test_plan05_task4_correction_b2b2.py":
        "packages/rakit-core/tests/test_action_concurrency.py",
    "packages/rakit-core/tests/test_plan05_task4_correction_c1.py":
        "packages/rakit-core/tests/test_action_operation_plans.py",
    "packages/rakit-core/tests/test_plan05_task4_correction_c2a_core.py":
        "packages/rakit-core/tests/test_operation_transactions.py",
    "packages/rakit-core/tests/test_plan05_task4_correction_e3.py":
        "packages/rakit-core/tests/test_action_advanced_results.py",
    "packages/rakit-core/tests/test_plan05_task5_bulk.py":
        "packages/rakit-core/tests/test_bulk_action_operations.py",
    "packages/rakit-core/tests/test_plan05_task6_pages.py":
        "packages/rakit-core/tests/test_page_operations.py",
    "packages/rakit-sqlalchemy/tests/test_plan05_task4_correction_c2a_sqlalchemy.py":
        "packages/rakit-sqlalchemy/tests/test_operation_uow_integration.py",
    "packages/rakit-sqlalchemy/tests/test_plan05_task4_correction_c2b.py":
        "packages/rakit-sqlalchemy/tests/test_action_mutations.py",
    "packages/rakit-sqlalchemy/tests/test_plan05_task4_correction_c2b_contract.py":
        "packages/rakit-sqlalchemy/tests/test_action_mutation_contracts.py",
    "packages/rakit-web/tests/test_plan05_task4_correction_c2a_web.py":
        "packages/rakit-web/tests/test_admin_transaction_composition.py",
    "packages/rakit/tests/test_plan05_bulk_facade.py":
        "packages/rakit/tests/test_bulk_facade.py",
    "packages/rakit/tests/test_plan05_pages_facade.py":
        "packages/rakit/tests/test_page_facade.py",
}


REPLACEMENTS: dict[str, list[tuple[str, str]]] = {
    "packages/rakit-core/tests/test_action_definition_contract.py": [
        (
            '"""PLAN 05 TASK 4 CORRECTION A: one canonical ``ActionDefinition`` contract.\n',
            '"""Canonical ``ActionDefinition`` contract.\n',
        ),
    ],
    "packages/rakit-core/tests/test_action_route_compilation.py": [
        (
            '"""PLAN 05 action-route compiler contract through Task 5.\n\n',
            '"""Action-route compiler contract across all supported scopes.\n\n',
        ),
        (
            'HTTP-method switch. Task 5 extends the Task 4 contract by making BULK routes\ncompiler-owned too.',
            'HTTP-method switch. BULK routes are compiler-owned too.',
        ),
    ],
    "packages/rakit-core/tests/test_action_concurrency.py": [
        (
            '"""PLAN 05 TASK 4 CORRECTION B2B2: generic RECORD concurrency for actions.\n\n',
            '"""Generic record concurrency contracts for actions.\n\n',
        ),
        (
            '``ActionDefinition.requires_concurrency`` is a Task-4 RECORD-only strong\nconcurrency flag; C2A additionally requires a mutating AUTO transaction. The\nruntime version capability remains a backend-neutral ``ConcurrencyVersionProvider``\nregistered per resource (Task 5 owns bulk concurrency snapshots).',
            '``ActionDefinition.requires_concurrency`` is a RECORD-only strong\nconcurrency flag and requires a mutating AUTO transaction. The runtime\nversion capability remains a backend-neutral ``ConcurrencyVersionProvider``\nregistered per resource; bulk actions own their concurrency snapshots.',
        ),
    ],
    "packages/rakit-core/tests/test_action_operation_plans.py": [
        (
            '"""PLAN 05 TASK 4 CORRECTION C1: canonical action OperationPlan mapping.\n\n',
            '"""Canonical action-to-OperationPlan mapping.\n\n',
        ),
        (
            'application execution boundary (RBAC never re-run in core).  C2A adds the\nexecutor capability contract: mutating AUTO/MANUAL requires UoW\nparticipation, and ``requires_concurrency`` means strong concurrency.',
            'application execution boundary (RBAC is never re-run in core). Mutating\nAUTO/MANUAL actions require UoW participation, and ``requires_concurrency``\nmeans strong concurrency.',
        ),
    ],
    "packages/rakit-core/tests/test_operation_transactions.py": [
        (
            '"""Plan 05 Task 4 Correction C2A: generic operation transaction lifecycle."""',
            '"""Generic operation transaction lifecycle."""',
        ),
    ],
    "packages/rakit-core/tests/test_action_advanced_results.py": [
        (
            '"""Correction E3: advanced action results remain durable AUTO successes."""',
            '"""Advanced action results remain durable AUTO successes."""',
        ),
    ],
    "packages/rakit-core/tests/test_bulk_action_operations.py": [
        (
            '"""Plan 05 Task 5 bulk action compiler and transaction contracts."""',
            '"""Bulk action compiler and transaction contracts."""',
        ),
    ],
    "packages/rakit-core/tests/test_page_operations.py": [
        (
            '"""Plan 05 Task 6 custom page execution and transaction contracts."""',
            '"""Custom page execution and transaction contracts."""',
        ),
    ],
    "packages/rakit-sqlalchemy/tests/test_operation_uow_integration.py": [
        (
            '"""Plan 05 Task 4 Correction C2A: real SQLAlchemy operation-UoW integration."""',
            '"""Real SQLAlchemy operation-UoW integration."""',
        ),
    ],
    "packages/rakit-sqlalchemy/tests/test_action_mutations.py": [
        (
            '"""Plan 05 Task 4 Correction C2B: sanctioned action -> SQLAlchemy mutation path."""',
            '"""Sanctioned action-to-SQLAlchemy mutation path."""',
        ),
    ],
    "packages/rakit-sqlalchemy/tests/test_action_mutation_contracts.py": [
        (
            '"""C2B capability guardrails for the sanctioned SQLAlchemy action executor."""',
            '"""Capability guardrails for the sanctioned SQLAlchemy action executor."""',
        ),
    ],
    "packages/rakit-web/tests/test_admin_transaction_composition.py": [
        (
            '"""Plan 05 Task 4 Correction C2A: real Admin transaction-capability composition."""',
            '"""Real Admin transaction-capability composition."""',
        ),
    ],
    "packages/rakit/tests/test_page_facade.py": [
        (
            '"""Public facade contract for Plan 05 Task 6 pages."""',
            '"""Public facade contract for custom pages."""',
        ),
    ],
    "packages/rakit-web/tests/test_page_admin_runtime.py": [
        (
            '"""Real Admin integration coverage for Plan 05 Task 6 pages."""',
            '"""Real Admin integration coverage for custom pages."""',
        ),
    ],
    "packages/rakit-web/tests/test_endpoints.py": [
        (
            '"""Plan 05 Task 7 typed custom endpoint regression coverage."""',
            '"""Typed custom endpoint regression coverage."""',
        ),
    ],
    "packages/rakit-web/tests/test_public_page_composition.py": [
        (
            '"""Public Admin composition contract for Plan 05 Task 6 pages."""',
            '"""Public Admin composition contract for custom pages."""',
        ),
    ],
    "packages/rakit-web/tests/test_page_input_guardrails.py": [
        (
            '"""Task 6 trust-boundary regression tests for custom Page input."""',
            '"""Trust-boundary regression tests for custom page input."""',
        ),
    ],
    "packages/rakit-web/tests/test_pages.py": [
        (
            '"""Plan 05 Task 6 web runtime regression coverage."""',
            '"""Custom page web runtime regression coverage."""',
        ),
    ],
    "packages/rakit-web/tests/test_page_runtime_validation.py": [
        (
            '"""Task 6 runtime-only Page capability validation."""',
            '"""Runtime-only custom page capability validation."""',
        ),
    ],
    "packages/rakit-web/tests/test_actions.py": [
        (
            '"""Plan 05 Task 4 unified actions: web translation and security contract tests."""',
            '"""Unified action web translation and security contract tests."""',
        ),
        (
            'pytest.raises(ValueError, match="Task 5")',
            'pytest.raises(ValueError, match="bulk action binding")',
        ),
    ],
    "packages/rakit-web/tests/test_bulk_actions.py": [
        (
            '"""Task 5 synchronous bulk action web lifecycle regressions."""',
            '"""Synchronous bulk action web lifecycle regressions."""',
        ),
    ],
    "tests/integration/rakit_integration.py": [
        (
            '"""Real ASGI + SQLAlchemy + file-backed SQLite integration fixture for Plan 05 Phase 3B.',
            '"""Real ASGI + SQLAlchemy + file-backed SQLite integration fixture.',
        ),
    ],
    "tests/integration/test_relationship_asgi_actions.py": [
        (
            '"""Plan 05 Task 4: real SQLAlchemy-backed record action through real HTTP."""',
            '"""Real SQLAlchemy-backed record action through real HTTP."""',
        ),
    ],
    "packages/rakit-core/src/rakit_core/bulk_actions.py": [
        (
            '"""Operation-plan builders for synchronous Plan 05 bulk actions."""',
            '"""Operation-plan builders for synchronous bulk actions."""',
        ),
    ],
    "packages/rakit-core/src/rakit_core/operations.py": [
        (
            '"""Immutable, backend-neutral execution seam for Plan 05 operations.',
            '"""Immutable, backend-neutral execution seam for operations.',
        ),
    ],
    "packages/rakit-core/src/rakit_core/mutations.py": [
        (
            '# identity while Plan 05 can use the capability for a non-CRUD operation.',
            '# identity while non-CRUD operations can use the capability.',
        ),
    ],
    "packages/rakit-core/src/rakit_core/compiler.py": [
        (
            '"""Keep Plan 05 resource child namespaces out of application route ownership.',
            '"""Keep resource child namespaces out of application route ownership.',
        ),
    ],
    "packages/rakit-core/src/rakit_core/actions.py": [
        (
            '"""Unified, backend-neutral action definitions and execution for Plan 05 Task 4.',
            '"""Unified, backend-neutral action definitions and execution.',
        ),
    ],
    "packages/rakit-core/src/rakit_core/relationship_mutations.py": [
        (
            '"""Semantic operations supported by the Plan 05 relationship executor."""',
            '"""Semantic operations supported by the relationship executor."""',
        ),
    ],
    "packages/rakit-core/src/rakit_core/pages.py": [
        (
            '"""Backend-neutral custom page execution primitives for Plan 05 Task 6.',
            '"""Backend-neutral custom page execution primitives.',
        ),
        (
            '"""Map a prepared page request to the canonical Plan 05 operation seam."""',
            '"""Map a prepared page request to the canonical operation seam."""',
        ),
    ],
    "packages/rakit-sqlalchemy/src/rakit_sqlalchemy/relationships.py": [
        (
            '"""SQLAlchemy mapper inspection for Plan 05 relationship metadata."""',
            '"""SQLAlchemy mapper inspection for relationship metadata."""',
        ),
    ],
    "packages/rakit-web/src/rakit_web/endpoint_routes.py": [
        (
            '"""Starlette runtime for compiler-owned Plan 05 Task 7 custom endpoints."""',
            '"""Starlette runtime for compiler-owned custom endpoints."""',
        ),
    ],
    "packages/rakit-web/src/rakit_web/endpoint_admin.py": [
        (
            '"""Public composition and Admin integration for Plan 05 Task 7 endpoints."""',
            '"""Public composition and Admin integration for custom endpoints."""',
        ),
    ],
    "packages/rakit-web/src/rakit_web/bulk_routes.py": [
        (
            '"""Synchronous web runtime for Plan 05 Task 5 BULK actions.',
            '"""Synchronous web runtime for BULK actions.',
        ),
    ],
    "packages/rakit-web/src/rakit_web/action_routes.py": [
        (
            '"""Web translation of unified Plan 05 Task 4 actions.',
            '"""Web translation of unified actions.',
        ),
        (
            '"BULK actions cannot be bound to routes until Task 5 selection exists"',
            '"BULK actions require a bulk action binding"',
        ),
    ],
    "packages/rakit-web/src/rakit_web/page_routes.py": [
        (
            '"""Web runtime for compiled Plan 05 Task 6 custom pages."""',
            '"""Web runtime for compiled custom pages."""',
        ),
    ],
    "packages/rakit-web/src/rakit_web/page_admin.py": [
        (
            '"""Admin composition helpers for compiled Plan 05 custom pages."""',
            '"""Admin composition helpers for compiled custom pages."""',
        ),
    ],
}


def rename_tests() -> None:
    for old_name, new_name in RENAMES.items():
        old = Path(old_name)
        new = Path(new_name)
        if old.exists():
            if new.exists():
                raise SystemExit(f"rename target already exists: {new}")
            old.rename(new)
        elif not new.exists():
            raise SystemExit(f"missing rename source and target: {old} -> {new}")


def remove_internal_docs() -> None:
    for directory in (Path("docs/plans"), Path("docs/specs"), Path("docs/design")):
        if directory.exists():
            shutil.rmtree(directory)


def apply_replacements() -> None:
    for filename, replacements in REPLACEMENTS.items():
        path = Path(filename)
        if not path.exists():
            raise SystemExit(f"expected file missing: {path}")
        text = path.read_text(encoding="utf-8")
        for old, new in replacements:
            if old in text:
                text = text.replace(old, new, 1)
        path.write_text(text, encoding="utf-8")


def update_gitignore() -> None:
    path = Path(".gitignore")
    text = path.read_text(encoding="utf-8").rstrip()
    block = (
        "# Internal planning and specification documents\n"
        "docs/plans/\n"
        "docs/specs/\n"
        "docs/design/"
    )
    if "docs/plans/" not in text:
        path.write_text(text + "\n\n" + block + "\n", encoding="utf-8")


def main() -> None:
    rename_tests()
    remove_internal_docs()
    apply_replacements()
    update_gitignore()


if __name__ == "__main__":
    main()
