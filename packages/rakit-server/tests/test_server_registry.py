from dataclasses import dataclass

import pytest

from rakit_server import (
    ServerAdapterNotFoundError,
    ServerCapabilities,
    ServerConfig,
    ServerRegistry,
    ServerTarget,
    run,
)


@dataclass
class FakeServer:
    name: str = "fake"
    capabilities: ServerCapabilities = ServerCapabilities()
    calls: list[tuple[ServerTarget, ServerConfig]] | None = None

    def __post_init__(self) -> None:
        if self.calls is None:
            self.calls = []

    def run(self, target: ServerTarget, config: ServerConfig) -> None:
        assert self.calls is not None
        self.calls.append((target, config))


async def app(scope: object, receive: object, send: object) -> None:
    del scope, receive, send


def test_registry_rejects_duplicate_explicit_adapter_names() -> None:
    registry = ServerRegistry(discover_entry_points=False)
    registry.register("fake", FakeServer)

    with pytest.raises(ValueError, match="already registered"):
        registry.register("fake", FakeServer)


def test_registry_reports_missing_adapter_without_fallback() -> None:
    registry = ServerRegistry(discover_entry_points=False)

    with pytest.raises(ServerAdapterNotFoundError, match='"missing"'):
        registry.create("missing")


def test_python_run_delegates_to_registered_adapter_with_portable_config() -> None:
    server = FakeServer()
    registry = ServerRegistry(discover_entry_points=False)
    registry.register("fake", lambda: server)

    run(
        app,
        server="fake",
        host="0.0.0.0",
        port=9000,
        workers=3,
        reload=True,
        log_level="warning",
        server_options={"native": "value"},
        registry=registry,
    )

    assert server.calls is not None
    assert len(server.calls) == 1
    target, config = server.calls[0]
    assert target.application is app
    assert config.host == "0.0.0.0"
    assert config.port == 9000
    assert config.workers == 3
    assert config.reload is True
    assert config.log_level == "warning"
    assert dict(config.server_options) == {"native": "value"}
