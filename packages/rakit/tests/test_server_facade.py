from typing import Any

import pytest
import rakit
from rakit_server import ServerAdapterNotFoundError


async def app(scope: object, receive: object, send: object) -> None:
    del scope, receive, send


def test_public_run_delegates_to_neutral_server_runtime(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[object, dict[str, Any]]] = []

    def fake_run(target: object, **kwargs: Any) -> None:
        calls.append((target, kwargs))

    monkeypatch.setattr("rakit._server._run_server", fake_run)

    rakit.run(
        app,
        server="granian",
        host="0.0.0.0",
        port=9000,
        workers=4,
        reload=True,
        log_level="warning",
        server_options={"backlog": 2048},
    )

    assert calls == [
        (
            app,
            {
                "server": "granian",
                "host": "0.0.0.0",
                "port": 9000,
                "workers": 4,
                "reload": True,
                "log_level": "warning",
                "server_options": {"backlog": 2048},
            },
        )
    ]


def test_public_run_gives_install_hint_for_known_optional_adapter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def missing(*args: object, **kwargs: object) -> None:
        del args, kwargs
        raise ServerAdapterNotFoundError('Server adapter "granian" is not installed or registered')

    monkeypatch.setattr("rakit._server._run_server", missing)

    with pytest.raises(ServerAdapterNotFoundError, match=r"rakit\[granian\]"):
        rakit.run("sample:admin", server="granian")
