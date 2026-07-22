import importlib
import re
import subprocess
import sys
import tomllib
from contextlib import asynccontextmanager
from pathlib import Path

import httpx

repository = Path(__file__).resolve().parents[2]


def test_minimal_example_compiles_without_optional_integrations() -> None:
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import sys; import examples.minimal.main as example; "
                "assert example.admin.compile().resources; "
                "assert 'fastapi' not in sys.modules; "
                "assert 'sqlalchemy' not in sys.modules"
            ),
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr


def test_fastapi_example_has_mounted_admin_and_compiles() -> None:
    module = importlib.import_module("examples.fastapi_sqlalchemy.main")

    assert module.app is not None
    assert module.admin.compile().resources
    assert any(getattr(route, "path", None) == "/admin" for route in module.app.routes)


def test_example_dependencies_are_declared_as_optional() -> None:
    repository = Path(__file__).resolve().parents[2]
    configuration = tomllib.loads((repository / "pyproject.toml").read_text(encoding="utf-8"))
    dependencies = configuration["project"]["optional-dependencies"]["examples"]

    assert any(dependency.startswith("fastapi") for dependency in dependencies)
    assert any(dependency.startswith("aiosqlite") for dependency in dependencies)
    assert any(dependency.startswith("uvicorn") for dependency in dependencies)


@asynccontextmanager
async def _started_client(app, *, base_url: str = "http://testserver"):
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url=base_url) as client:
            yield client


async def test_minimal_example_serves_read_routes_and_actual_query_contract() -> None:
    module = importlib.import_module("examples.minimal.main")
    transport = httpx.ASGITransport(app=module.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        full = await client.get(
            "/products",
            params={
                "filter": "name:contains:Clamp",
                "sort": "-name",
                "page": "1",
                "per_page": "1",
                "count_policy": "exact",
            },
        )
        fragment = await client.get(
            "/products",
            params={"sort": "name", "count_policy": "disabled"},
            headers={"HX-Request": "true"},
        )
        deferred = await client.get(
            "/products",
            params={"filter": "name:contains:Clamp", "count_policy": "deferred"},
        )
        count = await client.get(
            "/products/_count",
            params={"filter": "name:contains:Clamp"},
            headers={"HX-Request": "true"},
        )

        detail_path = re.search(r'href="(/products/[^"]+)"', full.text)
        assert detail_path is not None
        detail = await client.get(detail_path.group(1))

    assert full.status_code == 200
    assert "Bench Clamp" in full.text
    assert "Soldering Iron" not in full.text
    assert "<html" in full.text
    assert fragment.status_code == 200
    assert "<html" not in fragment.text
    assert "Total unknown" in fragment.text
    assert "Calculating total" in deferred.text
    assert count.text.strip() == "1"
    assert detail.status_code == 200
    assert "Bench Clamp" in detail.text


async def test_fastapi_sqlalchemy_example_mount_serves_full_and_htmx_reads() -> None:
    module = importlib.import_module("examples.fastapi_sqlalchemy.main")

    async with _started_client(module.app) as client:
        full = await client.get(
            "/admin/users",
            params={
                "filter": "name:contains:a",
                "sort": "-name",
                "page": "1",
                "per_page": "1",
                "count_policy": "exact",
            },
        )
        fragment = await client.get(
            "/admin/users",
            params={"search": "example.com", "count_policy": "disabled"},
            headers={"HX-Request": "true"},
        )
        deferred = await client.get(
            "/admin/users",
            params={"search": "work.test", "count_policy": "deferred"},
        )
        count = await client.get(
            "/admin/users/_count",
            params={"search": "work.test"},
            headers={"HX-Request": "true"},
        )

        asset_paths = re.findall(r'(?:href|src)="(/admin/_system/static/[^"]+)"', full.text)
        asset_responses = [await client.get(path) for path in asset_paths]

        detail_path = re.search(r'href="(/admin/users/[^"]+)"', full.text)
        assert detail_path is not None
        detail = await client.get(detail_path.group(1))

    assert full.status_code == 200
    assert "<html" in full.text
    assert "Grace" in full.text
    assert len(asset_paths) == 2
    assert all(response.status_code == 200 for response in asset_responses)
    assert fragment.status_code == 200
    assert "<html" not in fragment.text
    assert "Total unknown" in fragment.text
    assert "Calculating total" in deferred.text
    assert count.text.strip() == "1"
    assert detail.status_code == 200
    assert "Grace" in detail.text


def test_cli_check_and_routes_accept_both_examples() -> None:
    for target in (
        "examples.minimal.main:admin",
        "examples.fastapi_sqlalchemy.main:admin",
    ):
        checked = subprocess.run(
            ["rakit", "check", target],
            cwd=repository,
            check=False,
            capture_output=True,
            text=True,
        )
        routes = subprocess.run(
            ["rakit", "routes", target],
            cwd=repository,
            check=False,
            capture_output=True,
            text=True,
        )

        assert checked.returncode == 0, checked.stderr
        assert "Rakit configuration is valid." in checked.stdout
        assert routes.returncode == 0, routes.stderr
        assert ":list" in routes.stdout
        assert ":detail" in routes.stdout
