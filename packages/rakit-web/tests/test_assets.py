import importlib
import re
import subprocess
import tarfile
import zipfile
from pathlib import Path

import httpx
from rakit import Admin, SecretValue


def _assets_module():
    return importlib.import_module("rakit_web.assets")


def test_static_url_uses_local_content_hashed_filenames() -> None:
    assets = _assets_module()

    assert re.fullmatch(r"/_system/static/rakit\.[0-9a-f]{8}\.css", assets.static_url("rakit.css"))
    assert re.fullmatch(
        r"/_system/static/htmx\.min\.[0-9a-f]{8}\.js",
        assets.static_url("htmx.min.js"),
    )


def test_static_url_rejects_unknown_or_path_names() -> None:
    assets = _assets_module()

    for name in ("missing.js", "../rakit.css", "nested/rakit.css"):
        try:
            assets.static_url(name)
        except KeyError:
            pass
        else:
            raise AssertionError(f"static_url accepted unsafe or unknown name: {name}")


async def test_admin_serves_only_hashed_immutable_assets() -> None:
    assets = _assets_module()
    admin = Admin(title="Assets", debug=False, secret_key=SecretValue("x" * 32))
    app = admin.asgi()
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://localhost") as client:
        css = await client.get(assets.static_url("rakit.css"))
        javascript = await client.get(assets.static_url("htmx.min.js"))
        raw = await client.get("/_system/static/htmx.min.js")
        missing = await client.get("/_system/static/missing.00000000.js")
        traversal = await client.get("/_system/static/%2e%2e/templates/base.html")

    immutable = "public, max-age=31536000, immutable"
    assert css.status_code == 200
    assert css.headers["cache-control"] == immutable
    assert css.headers["content-type"].startswith("text/css")
    assert javascript.status_code == 200
    assert javascript.headers["cache-control"] == immutable
    assert "javascript" in javascript.headers["content-type"]
    assert raw.status_code == 404
    assert missing.status_code == 404
    assert traversal.status_code == 404


def test_rakit_web_artifacts_include_runtime_resources(tmp_path: Path) -> None:
    repository = Path(__file__).resolve().parents[3]
    output = tmp_path / "dist"
    subprocess.run(
        ["uv", "build", "--package", "rakit-web", "--out-dir", str(output)],
        cwd=repository,
        check=True,
        capture_output=True,
        text=True,
    )

    wheel = next(output.glob("rakit_web-*.whl"))
    sdist = next(output.glob("rakit_web-*.tar.gz"))
    expected_suffixes = {
        "rakit_web/assets.py",
        "rakit_web/static/rakit.css",
        "rakit_web/static/htmx.min.js",
        "rakit_web/static/HTMX_LICENSE.txt",
        "rakit_web/static/HTMX_PROVENANCE.md",
        "rakit_web/templates/base.html",
        "rakit_web/templates/resources/_count.html",
        "rakit_web/templates/resources/_table.html",
        "rakit_web/templates/resources/detail.html",
        "rakit_web/templates/resources/list.html",
    }

    with zipfile.ZipFile(wheel) as archive:
        wheel_names = set(archive.namelist())
    assert all(any(name.endswith(suffix) for name in wheel_names) for suffix in expected_suffixes)

    with tarfile.open(sdist, mode="r:gz") as archive:
        sdist_names = {member.name for member in archive.getmembers()}
    assert all(any(name.endswith(suffix) for name in sdist_names) for suffix in expected_suffixes)
