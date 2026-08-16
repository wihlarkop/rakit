from typing import cast

import pytest
from rakit_server import ServerCapabilities, ServerConfig


def test_server_config_normalizes_portable_options_and_freezes_native_options() -> None:
    native = {"backlog": 2048}
    config = ServerConfig(
        host="0.0.0.0",
        port=9000,
        workers=4,
        reload=True,
        log_level="debug",
        server_options=native,
    )
    native["backlog"] = 1024

    assert config.host == "0.0.0.0"
    assert config.port == 9000
    assert config.workers == 4
    assert config.reload is True
    assert config.log_level == "debug"
    assert dict(config.server_options) == {"backlog": 2048}

    runtime_mapping = cast(dict[str, object], config.server_options)
    with pytest.raises(TypeError):
        runtime_mapping["backlog"] = 512


def test_server_config_rejects_invalid_port_workers_and_native_option_names() -> None:
    with pytest.raises(ValueError, match="port"):
        ServerConfig(port=0)

    with pytest.raises(ValueError, match="workers"):
        ServerConfig(workers=0)

    with pytest.raises(ValueError, match="server option"):
        ServerConfig(server_options={"": True})


def test_server_capabilities_require_blocking_run_and_publish_generic_capabilities() -> None:
    capabilities = ServerCapabilities(
        reload=True,
        workers=True,
        app_object=True,
        import_string=True,
    )

    assert capabilities.capability_set.names == (
        "server.blocking-run",
        "server.reload",
        "server.target.import-string",
        "server.target.object",
        "server.workers",
    )

    with pytest.raises(ValueError, match="blocking run"):
        ServerCapabilities(blocking_run=False)
