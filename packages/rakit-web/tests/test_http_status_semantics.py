import re
from pathlib import Path


_NUMERIC_STATUS_CODE = re.compile(r"\bstatus_code\s*(?:==|!=|<=|>=|=|<|>)\s*\d{3}\b")


def test_web_runtime_uses_semantic_http_status_values() -> None:
    source_root = Path(__file__).resolve().parents[1] / "src" / "rakit_web"
    violations: list[str] = []

    for path in sorted(source_root.rglob("*.py")):
        for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if _NUMERIC_STATUS_CODE.search(line):
                violations.append(f"{path.relative_to(source_root)}:{line_number}: {line.strip()}")

    assert not violations, "numeric HTTP status_code literals remain:\n" + "\n".join(violations)


def test_major_http_translation_modules_use_httpstatus() -> None:
    source_root = Path(__file__).resolve().parents[1] / "src" / "rakit_web"

    for relative in ("admin.py", "action_routes.py", "generated_rest_runtime.py"):
        source = (source_root / relative).read_text(encoding="utf-8")
        assert "from http import HTTPStatus" in source
        assert "HTTPStatus." in source
