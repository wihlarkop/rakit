from typing import Any

import pytest
import rakit_server_granian
from granian.constants import Interfaces
from granian.log import LogLevels
from rakit_server import ServerConfig, ServerConfigurationError
from rakit_server_granian.server import GranianServer


async def app(scope: object, receive: object, send: object) -> None:
    del scope, receive, send


def test_package_root_exports_granian_server() -> None:
    assert rakit_server_granian.GranianServer is GranianServer
    assert GranianServer.name == "granian"
    assert GranianServer.capabilities.import_string is True
    assert GranianServer.capabilities.app_object is False
    assert GranianServer.capabilities.async_serve is False


def test_run_maps_portable_config_and_uses_rakit_worker_loader(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    constructed: list[dict[str, Any]] = []
    loaded: list[str] = []

    class FakeGranian:
        def __init__(self, **kwargs: Any) -> None:
            constructed.append(kwargs)

        def serve(self, *, target_loader) -> None:
            assert target_loader("sample:admin") is app

    def fake_load(spec: str):
        loaded.append(spec)
        return app

    monkeypatch.setattr("rakit_server_granian.server.Granian", FakeGranian)
    monkeypatch.setattr("rakit_server_granian.server.load_application", fake_load)

    GranianServer().run(
        "sample:admin",
        ServerConfig(
            host="0.0.0.0",
            port=9000,
            workers=3,
            reload=True,
            log_level="warning",
            server_options={"backlog": 2048},
        ),
    )

    assert loaded == ["sample:admin"]
    assert constructed == [
        {
            "target": "sample:admin",
            "address": "0.0.0.0",
            "port": 9000,
            "interface": Interfaces.ASGI,
            "workers": 3,
            "reload": True,
            "log_level": LogLevels.warning,
            "backlog": 2048,
        }
    ]


def test_constructor_config_supports_direct_programmatic_use(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    constructed: list[dict[str, Any]] = []

    class FakeGranian:
        def __init__(self, **kwargs: Any) -> None:
            constructed.append(kwargs)

        def serve(self, *, target_loader) -> None:
            del target_loader

    monkeypatch.setattr("rakit_server_granian.server.Granian", FakeGranian)

    GranianServer(host="0.0.0.0", port=9100).run("sample:admin")

    assert constructed[0]["address"] == "0.0.0.0"
    assert constructed[0]["port"] == 9100


def test_object_target_fails_closed_instead_of_using_experimental_embedding() -> None:
    with pytest.raises(ServerConfigurationError, match="import-string"):
        GranianServer().run(app)


def test_native_options_cannot_override_asgi_interface_or_portable_options() -> None:
    with pytest.raises(ServerConfigurationError, match="interface"):
        GranianServer().run(
            "sample:admin",
            ServerConfig(server_options={"interface": "rsgi"}),
        )


def test_multiple_workers_on_windows_fail_instead_of_silent_downgrade(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("rakit_server_granian.server.sys.platform", "win32")

    with pytest.raises(ServerConfigurationError, match="Windows"):
        GranianServer().run("sample:admin", ServerConfig(workers=2))
