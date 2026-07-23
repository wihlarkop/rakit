import html
import importlib
import os
import re
import subprocess
import sys
import tomllib
import zipfile
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, cast

import httpx
import pytest
from rakit import Admin
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

repository = Path(__file__).resolve().parents[2]


def _example_environment() -> dict[str, str]:
    environment = os.environ.copy()
    existing = environment.get("PYTHONPATH")
    entries = [str(repository)]
    if existing:
        entries.append(existing)
    environment["PYTHONPATH"] = os.pathsep.join(entries)
    return environment


@pytest.fixture(autouse=True)
def _private_example_import_path(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.syspath_prepend(str(repository))


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
        env=_example_environment(),
    )

    assert result.returncode == 0, result.stderr


def test_readme_primary_example_executes_and_compiles_without_io() -> None:
    readme = (repository / "README.md").read_text(encoding="utf-8")
    section = readme.split("## Example direction", 1)[1]
    match = re.search(r"```python\s+(.*?)```", section, flags=re.DOTALL)
    assert match is not None

    class DocumentationBase(DeclarativeBase):
        pass

    class DocumentationUser(DocumentationBase):
        __tablename__ = "documentation_users"

        id: Mapped[int] = mapped_column(primary_key=True)

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    namespace: dict[str, Any] = {"engine": engine, "User": DocumentationUser}

    exec(compile(match.group(1), "README.md", "exec"), namespace)

    admin = cast(Admin, namespace["admin"])
    compiled = admin.compile()
    assert [resource.resource_id for resource in compiled.resources] == ["users"]
    assert namespace["app"] is not None


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


def test_fastapi_example_is_type_checkable_in_the_locked_development_environment() -> None:
    configuration = tomllib.loads((repository / "pyproject.toml").read_text(encoding="utf-8"))
    development_dependencies = configuration["dependency-groups"]["dev"]

    assert any(dependency.startswith("fastapi") for dependency in development_dependencies)


def test_fastapi_is_not_an_official_package_runtime_dependency() -> None:
    for package_configuration in (repository / "packages").glob("*/pyproject.toml"):
        configuration = tomllib.loads(package_configuration.read_text(encoding="utf-8"))
        runtime_dependencies = configuration["project"].get("dependencies", [])

        assert not any(dependency.startswith("fastapi") for dependency in runtime_dependencies)


@asynccontextmanager
async def _started_client(app, *, base_url: str = "http://localhost"):
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url=base_url) as client:
            yield client


async def test_minimal_example_serves_read_routes_and_actual_query_contract() -> None:
    module = importlib.import_module("examples.minimal.main")
    transport = httpx.ASGITransport(app=module.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://localhost") as client:
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

        search_action_match = re.search(
            r'<form[^>]+data-rakit-search[^>]+action="([^"]+)"', full.text
        )
        assert search_action_match is not None
        search_action = html.unescape(search_action_match.group(1))
        search_response = await client.get(search_action, params={"search": "Ada"})

        sort_href_match = re.search(r'<th[^>]*>\s*<a href="([^"]+)"', full.text)
        assert sort_href_match is not None
        sort_href = html.unescape(sort_href_match.group(1))
        sort_response = await client.get(sort_href)

        detail_path = re.search(r'href="(/admin/users/[^"]+)"', full.text)
        assert detail_path is not None
        detail = await client.get(detail_path.group(1))

    assert full.status_code == 200
    assert "<html" in full.text
    assert "Grace" in full.text
    assert len(asset_paths) == 2
    assert all(response.status_code == 200 for response in asset_responses)
    assert search_action == "/admin/users"
    assert search_response.status_code == 200
    assert sort_href.startswith("/admin/users?")
    assert sort_response.status_code == 200
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
            env=_example_environment(),
        )
        routes = subprocess.run(
            ["rakit", "routes", target],
            cwd=repository,
            check=False,
            capture_output=True,
            text=True,
            env=_example_environment(),
        )

        assert checked.returncode == 0, checked.stderr
        assert "Rakit configuration is valid." in checked.stdout
        assert routes.returncode == 0, routes.stderr
        assert ":list" in routes.stdout
        assert ":detail" in routes.stdout


def test_all_packages_builds_exactly_the_eight_official_distributions(tmp_path: Path) -> None:
    output = tmp_path / "all-distributions"
    subprocess.run(
        ["uv", "build", "--all-packages", "--out-dir", str(output)],
        cwd=repository,
        check=True,
        capture_output=True,
        text=True,
    )

    expected = {
        "rakit",
        "rakit_auth_sqlalchemy",
        "rakit_core",
        "rakit_server_uvicorn",
        "rakit_sqlalchemy",
        "rakit_storage",
        "rakit_storage_local",
        "rakit_web",
    }
    wheels = {path.name.split("-", 1)[0] for path in output.glob("*.whl")}
    sdists = {path.name.split("-", 1)[0] for path in output.glob("*.tar.gz")}

    assert wheels == expected
    assert sdists == expected
    assert not any(path.name.startswith("rakit_workspace-") for path in output.iterdir())

    rakit_wheel = next(output.glob("rakit-*.whl"))
    with zipfile.ZipFile(rakit_wheel) as archive:
        assert "rakit/py.typed" in archive.namelist()

    installed = tmp_path / "installed-rakit"
    subprocess.run(
        ["uv", "venv", str(installed), "--python", sys.executable],
        check=True,
        capture_output=True,
        text=True,
    )
    installed_python = installed / "Scripts" / "python.exe"
    subprocess.run(
        [
            "uv",
            "pip",
            "install",
            "--python",
            str(installed_python),
            "--find-links",
            str(output),
            str(rakit_wheel),
            "--offline",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    isolated_environment = os.environ.copy()
    isolated_environment.pop("PYTHONPATH", None)
    imported = subprocess.run(
        [
            str(installed_python),
            "-c",
            (
                "import sys; "
                "from rakit.core import (CountPolicy, DataSource, DataSourceCapabilities, Filter, "
                "FilterOperator, IdentityCodec, NullPlacement, OffsetPagination, PageResult, "
                "RecordIdentity, ResourceQuery, ResourceService, Sort, SortDirection); "
                "assert 'rakit_sqlalchemy' not in sys.modules"
            ),
        ],
        cwd=installed,
        env=isolated_environment,
        check=False,
        capture_output=True,
        text=True,
    )
    assert imported.returncode == 0, imported.stderr
