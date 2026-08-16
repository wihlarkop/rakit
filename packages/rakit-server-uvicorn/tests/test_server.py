from typing import Any

import pytest
import rakit_server_uvicorn
from rakit_server import ServerConfig, ServerConfigurationError
from rakit_server_uvicorn.server import UvicornServer


async def app(scope: object, receive: object, send: object) -> None:
    del scope, receive, send


def test_package_root_exports_uvicorn_server() -> None:
    assert rakit_server_uvicorn.UvicornServer is UvicornServer
    assert UvicornServer.name == "uvicorn"
    assert UvicornServer.capabilities.async_serve is True
    assert UvicornServer.capabilities.graceful_stop is True


def test_run_maps_portable_config_to_uvicorn(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[Any, dict[str, Any]]] = []

    def fake_run(application: Any, **kwargs: Any) -> None:
        calls.append((application, kwargs))

    monkeypatch.setattr("rakit_server_uvicorn.server.uvicorn.run", fake_run)
    server = UvicornServer()
    server.run(
        app,
        ServerConfig(
            host="0.0.0.0",
            port=9000,
            workers=1,
            log_level="warning",
            server_options={"backlog": 2048},
        ),
    )

    assert calls == [
        (
            app,
            {
                "host": "0.0.0.0",
                "port": 9000,
                "workers": 1,
                "reload": False,
                "log_level": "warning",
                "backlog": 2048,
            },
        )
    ]


def test_constructor_config_supports_direct_programmatic_use(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[Any, dict[str, Any]]] = []
    monkeypatch.setattr(
        "rakit_server_uvicorn.server.uvicorn.run",
        lambda application, **kwargs: calls.append((application, kwargs)),
    )

    UvicornServer(host="0.0.0.0", port=9100).run(app)

    assert calls[0][0] is app
    assert calls[0][1]["host"] == "0.0.0.0"
    assert calls[0][1]["port"] == 9100


def test_constructor_target_remains_supported_for_existing_programmatic_users(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[Any] = []
    monkeypatch.setattr("rakit_server_uvicorn.server.load_application", lambda spec: app)
    monkeypatch.setattr(
        "rakit_server_uvicorn.server.uvicorn.run",
        lambda application, **kwargs: calls.append(application),
    )

    UvicornServer(app="sample:admin").run()

    assert calls == [app]


def test_constructor_and_run_targets_cannot_be_combined() -> None:
    with pytest.raises(ServerConfigurationError, match="both"):
        UvicornServer(app="sample:admin").run(app)


def test_run_rejects_reload_with_multiple_workers() -> None:
    with pytest.raises(ServerConfigurationError, match="mutually exclusive"):
        UvicornServer().run("sample:app", ServerConfig(reload=True, workers=2))


def test_run_rejects_object_target_when_process_supervision_needs_import_string() -> None:
    with pytest.raises(ServerConfigurationError, match="import-string"):
        UvicornServer().run(app, ServerConfig(workers=2))


def test_run_rejects_native_override_of_portable_options() -> None:
    with pytest.raises(ServerConfigurationError, match="host"):
        UvicornServer().run(app, ServerConfig(server_options={"host": "localhost"}))


def test_single_process_import_string_is_loaded_by_rakit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[Any] = []
    monkeypatch.setattr("rakit_server_uvicorn.server.load_application", lambda spec: app)
    monkeypatch.setattr(
        "rakit_server_uvicorn.server.uvicorn.run",
        lambda application, **kwargs: calls.append(application),
    )

    UvicornServer().run("sample:admin")

    assert calls == [app]


@pytest.mark.anyio
async def test_async_serve_uses_uvicorn_server_and_stop_requests_shutdown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []

    class FakeConfig:
        def __init__(self, application: object, **kwargs: object) -> None:
            assert application is app
            assert kwargs["host"] == "127.0.0.1"

    class FakeServer:
        def __init__(self, config: object) -> None:
            del config
            self.should_exit = False

        async def serve(self) -> None:
            events.append("serve")
            server.stop()
            assert self.should_exit is True

    monkeypatch.setattr("rakit_server_uvicorn.server.uvicorn.Config", FakeConfig)
    monkeypatch.setattr("rakit_server_uvicorn.server.uvicorn.Server", FakeServer)
    server = UvicornServer()

    await server.serve(app)

    assert events == ["serve"]
