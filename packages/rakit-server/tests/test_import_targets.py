from pathlib import Path

import pytest
from rakit_server import load_application
from rakit_server.errors import InvalidServerTargetError


def test_load_application_resolves_admin_like_target(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "sample_target.py").write_text(
        "async def app(scope, receive, send):\n"
        "    pass\n"
        "class AdminLike:\n"
        "    def asgi(self):\n"
        "        return app\n"
        "admin = AdminLike()\n",
        encoding="utf-8",
    )
    monkeypatch.syspath_prepend(str(tmp_path))

    application = load_application("sample_target:admin")

    assert callable(application)


def test_load_application_reports_missing_attribute(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "missing_target.py").write_text("value = 1\n", encoding="utf-8")
    monkeypatch.syspath_prepend(str(tmp_path))

    with pytest.raises(InvalidServerTargetError, match="Unable to import"):
        load_application("missing_target:app")
