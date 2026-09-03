from __future__ import annotations

from pathlib import Path

import pytest
from rakit_web._host_conformance import (
    ASGIHostConformanceCase,
    run_host_conformance,
)
from rakit_web.asgi_composition import compose_asgi


class _ProbeRakit:
    def __init__(self, admin: _ProbeAdmin) -> None:
        self.admin = admin

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] == "lifespan":
            message = await receive()
            assert message["type"] == "lifespan.startup"
            for callback in self.admin._startup_callbacks:
                await callback()
            scope["state"]["conformance.rakit"] = True
            await send({"type": "lifespan.startup.complete"})
            message = await receive()
            assert message["type"] == "lifespan.shutdown"
            for callback in reversed(self.admin._shutdown_callbacks):
                await callback()
            await send({"type": "lifespan.shutdown.complete"})
            return

        assert scope["path"] == "/"
        assert "conformance.host" not in scope["state"]
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"rakit"})


class _ProbeAdmin:
    def __init__(self) -> None:
        self._startup_callbacks = []
        self._shutdown_callbacks = []
        self._app = _ProbeRakit(self)

    def on_startup(self, callback):
        self._startup_callbacks.append(callback)

    def on_shutdown(self, callback):
        self._shutdown_callbacks.append(callback)

    def asgi(self):
        return self._app


@pytest.mark.anyio
async def test_d4_host_conformance_is_reusable_without_host_framework_imports() -> None:
    def build_admin() -> _ProbeAdmin:
        return _ProbeAdmin()

    case = ASGIHostConformanceCase(
        name="probe-host",
        build_admin=build_admin,
        compose=lambda host, admin: compose_asgi(host, admin, path="/admin"),
    )

    result = await run_host_conformance(case)

    assert result.case_name == "probe-host"
    assert result.host_status == 200
    assert result.rakit_status == 200
    assert result.lifecycle_events == (
        "host.startup",
        "rakit.startup",
        "rakit.shutdown",
        "host.shutdown",
    )


def test_generic_d4_production_modules_have_no_host_framework_leakage() -> None:
    source_root = Path(__file__).parents[1] / "src" / "rakit_web"
    for module_name in ("asgi_composition.py", "_host_conformance.py"):
        source = (source_root / module_name).read_text(encoding="utf-8").lower()
        for framework_name in ("fastapi", "litestar", "sanic", "flask"):
            assert framework_name not in source
