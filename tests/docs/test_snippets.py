"""Keep marked documentation snippets executable and public-import-only."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

_RUNNABLE = re.compile(r"```python runnable\n(.*?)```", re.DOTALL)
_PRIVATE_IMPORT = re.compile(r"(?:from|import)\s+[A-Za-z0-9_.]+\._[A-Za-z0-9_]+")


def _repository() -> Path:
    return Path(__file__).resolve().parents[2]


def _runnable_snippets() -> list[tuple[str, str]]:
    repository = _repository()
    snippets: list[tuple[str, str]] = []
    for document in sorted((repository / "docs").rglob("*.md")):
        for index, match in enumerate(_RUNNABLE.finditer(document.read_text(encoding="utf-8")), 1):
            snippets.append((f"{document.relative_to(repository)}:{index}", match.group(1)))
    return snippets


def test_docs_have_at_least_one_runnable_quickstart() -> None:
    assert _runnable_snippets(), "mark executable docs with ```python runnable"


@pytest.mark.parametrize(("label", "source"), _runnable_snippets())
def test_runnable_documentation_snippet(
    label: str,
    source: str,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    repository = _repository()
    monkeypatch.syspath_prepend(str(repository))
    monkeypatch.chdir(tmp_path)
    assert _PRIVATE_IMPORT.search(source) is None, f"{label} imports a private module"
    code = compile(source, label, "exec")
    namespace: dict[str, object] = {"__name__": "__rakit_docs_snippet__"}
    exec(code, namespace, namespace)
