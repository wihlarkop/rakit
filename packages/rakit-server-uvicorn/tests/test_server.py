from typing import Any

import pytest
import rakit_server_uvicorn
from rakit_server_uvicorn.server import UvicornServer


def test_package_root_exports_uvicorn_server() -> None:
    assert rakit_server_uvicorn.UvicornServer is UvicornServer


def test_run_applies_supported_option_override(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[Any, dict[str, Any]]] = []

    def fake_run(app: Any, **kwargs: Any) -> None:
        calls.append((app, kwargs))

    monkeypatch.setattr("rakit_server_uvicorn.server.uvicorn.run", fake_run)

    server = UvicornServer(app="myapp:app", host="0.0.0.0", port=8000)
    server.run(port=9000)

    assert len(calls) == 1
    app, kwargs = calls[0]
    assert app == "myapp:app"
    assert kwargs["port"] == 9000
    assert kwargs["host"] == "0.0.0.0"
    assert kwargs["reload"] is False


def test_run_rejects_unsupported_option_without_calling_uvicorn(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[Any, dict[str, Any]]] = []

    def fake_run(app: Any, **kwargs: Any) -> None:
        calls.append((app, kwargs))

    monkeypatch.setattr("rakit_server_uvicorn.server.uvicorn.run", fake_run)

    server = UvicornServer(app="myapp:app")

    with pytest.raises(ValueError, match="workers"):
        server.run(workers=4)

    assert calls == []


def test_run_rejects_app_override_without_calling_uvicorn(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[Any, dict[str, Any]]] = []

    def fake_run(app: Any, **kwargs: Any) -> None:
        calls.append((app, kwargs))

    monkeypatch.setattr("rakit_server_uvicorn.server.uvicorn.run", fake_run)

    server = UvicornServer(app="myapp:app")

    with pytest.raises(ValueError, match="app"):
        server.run(app="something-else")

    assert calls == []
