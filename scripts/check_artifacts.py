#!/usr/bin/env python3
"""Build and inspect every official Rakit distribution in an isolated release smoke.

The checker intentionally derives the package inventory from ``packages/*/pyproject.toml`` rather
than keeping an independent package count. It builds into a temporary directory, inspects wheels
and sdists, installs ``rakit[standard]`` from those local wheels into a clean virtual environment,
and starts a copied minimal example outside the repository working tree.
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import socket
import subprocess
import sys
import tarfile
import tempfile
import time
import tomllib
import zipfile
from dataclasses import dataclass
from email.parser import Parser
from pathlib import Path, PurePosixPath

VERSION = "0.1.0a1"
_INTERNAL_PREFIX = "rakit"
_SECRET_PATTERNS = (
    re.compile(rb"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    re.compile(rb"AKIA[0-9A-Z]{16}"),
    re.compile(rb"sk_live_[0-9A-Za-z]{16,}"),
)
_FORBIDDEN_PARTS = {"tests", "test", "__pycache__", ".pytest_cache"}
_FORBIDDEN_NAMES = {".env", ".env.local", "id_rsa", "id_ed25519"}
_REQUIRED_WHEEL_PATHS: dict[str, tuple[str, ...]] = {
    "rakit-web": (
        "rakit_web/templates/base.html",
        "rakit_web/static/rakit.css",
        "rakit_web/static/rakit-ui.js",
        "rakit_web/static/theme.js",
    ),
    "rakit-auth-sqlalchemy": (
        "rakit_auth_sqlalchemy/alembic.ini",
        "rakit_auth_sqlalchemy/alembic/env.py",
    ),
}
_STANDARD_MODULES = (
    "rakit",
    "rakit.core",
    "rakit.sqlalchemy",
    "rakit.auth.sqlalchemy",
    "rakit_core",
    "rakit_core.testing",
    "rakit_web",
    "rakit_sqlalchemy",
    "rakit_auth_sqlalchemy",
    "rakit_storage",
    "rakit_storage_local",
    "rakit_server",
    "rakit_server_uvicorn",
)


@dataclass(frozen=True)
class Project:
    name: str
    version: str
    root: Path
    import_root: str


@dataclass(frozen=True)
class Artifact:
    project: Project
    wheel: Path
    sdist: Path


def repository_root() -> Path:
    return Path(__file__).resolve().parents[1]


def discover_projects(root: Path) -> tuple[Project, ...]:
    projects: list[Project] = []
    for pyproject in sorted((root / "packages").glob("*/pyproject.toml")):
        data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
        project = data.get("project", {})
        name = str(project.get("name", ""))
        version = str(project.get("version", ""))
        if not name.startswith(_INTERNAL_PREFIX):
            raise RuntimeError(f"unexpected workspace distribution {name!r} at {pyproject}")
        source_dirs = sorted((pyproject.parent / "src").glob("*/py.typed"))
        if len(source_dirs) != 1:
            raise RuntimeError(f"{name} must contain exactly one typed import package")
        projects.append(
            Project(
                name=name,
                version=version,
                root=pyproject.parent,
                import_root=source_dirs[0].parent.name,
            )
        )
    if not projects:
        raise RuntimeError("no official distributions discovered")
    names = [project.name for project in projects]
    if len(names) != len(set(names)):
        raise RuntimeError("duplicate official distribution name")
    return tuple(projects)


def _run(
    command: list[str],
    *,
    cwd: Path,
    env: dict[str, str] | None = None,
    timeout: float | None = None,
) -> subprocess.CompletedProcess[str]:
    print("+", " ".join(command), flush=True)
    return subprocess.run(
        command,
        cwd=cwd,
        env=env,
        text=True,
        check=True,
        capture_output=True,
        timeout=timeout,
    )


def build_projects(projects: tuple[Project, ...], output: Path, root: Path) -> tuple[Artifact, ...]:
    output.mkdir(parents=True, exist_ok=True)
    artifacts: list[Artifact] = []
    for project in projects:
        if project.version != VERSION:
            raise RuntimeError(f"{project.name}: expected {VERSION}, found {project.version}")
        before = set(output.iterdir())
        _run(["uv", "build", str(project.root), "--out-dir", str(output)], cwd=root)
        created = set(output.iterdir()) - before
        wheels = sorted(path for path in created if path.suffix == ".whl")
        sdists = sorted(path for path in created if path.name.endswith(".tar.gz"))
        if len(wheels) != 1 or len(sdists) != 1:
            raise RuntimeError(
                f"{project.name}: expected one wheel and one sdist, got {wheels!r} / {sdists!r}"
            )
        artifacts.append(Artifact(project=project, wheel=wheels[0], sdist=sdists[0]))
    return tuple(artifacts)


def _metadata_from_wheel(wheel: zipfile.ZipFile) -> tuple[str, str, tuple[str, ...]]:
    metadata_files = [name for name in wheel.namelist() if name.endswith(".dist-info/METADATA")]
    if len(metadata_files) != 1:
        raise RuntimeError("wheel must contain exactly one METADATA file")
    metadata = Parser().parsestr(wheel.read(metadata_files[0]).decode("utf-8"))
    return (
        str(metadata["Name"]),
        str(metadata["Version"]),
        tuple(metadata.get_all("Requires-Dist", [])),
    )


def _assert_internal_dependencies_pinned(project: Project, requirements: tuple[str, ...]) -> None:
    for requirement in requirements:
        name_match = re.match(r"([A-Za-z0-9_.-]+)", requirement)
        if name_match is None:
            continue
        dependency = name_match.group(1).lower().replace("_", "-")
        if dependency.startswith("rakit") and f"=={VERSION}" not in requirement:
            raise RuntimeError(
                f"{project.name}: internal dependency must pin =={VERSION}: {requirement}"
            )


def inspect_wheel(artifact: Artifact) -> None:
    with zipfile.ZipFile(artifact.wheel) as wheel:
        names = wheel.namelist()
        name, version, requirements = _metadata_from_wheel(wheel)
        if name.lower().replace("_", "-") != artifact.project.name:
            raise RuntimeError(f"wheel name mismatch for {artifact.project.name}: {name}")
        if version != VERSION:
            raise RuntimeError(f"{artifact.project.name}: wheel version is {version}")
        typed = f"{artifact.project.import_root}/py.typed"
        if typed not in names:
            raise RuntimeError(f"{artifact.project.name}: wheel missing {typed}")

        for item in names:
            path = PurePosixPath(item)
            lowered = {part.lower() for part in path.parts}
            if lowered & _FORBIDDEN_PARTS:
                raise RuntimeError(f"{artifact.project.name}: wheel unexpectedly contains {item}")
            if path.name.lower() in _FORBIDDEN_NAMES or path.suffix.lower() in {".pem", ".key"}:
                raise RuntimeError(f"{artifact.project.name}: suspicious credential file {item}")

        for required in _REQUIRED_WHEEL_PATHS.get(artifact.project.name, ()):
            if required not in names:
                raise RuntimeError(
                    f"{artifact.project.name}: wheel missing required asset {required}"
                )
        if artifact.project.name == "rakit-auth-sqlalchemy" and not any(
            name.startswith("rakit_auth_sqlalchemy/alembic/versions/") and name.endswith(".py")
            for name in names
        ):
            raise RuntimeError("rakit-auth-sqlalchemy: wheel contains no Alembic revisions")

        _assert_internal_dependencies_pinned(artifact.project, requirements)
        for item in names:
            if item.endswith("/"):
                continue
            info = wheel.getinfo(item)
            if info.file_size > 2_000_000:
                continue
            payload = wheel.read(item)
            if any(pattern.search(payload) for pattern in _SECRET_PATTERNS):
                raise RuntimeError(f"{artifact.project.name}: secret-like material in {item}")


def inspect_sdist(artifact: Artifact) -> None:
    with tarfile.open(artifact.sdist, "r:gz") as archive:
        members = [member for member in archive.getmembers() if member.isfile()]
        if not members:
            raise RuntimeError(f"{artifact.project.name}: empty sdist")
        pyprojects = [
            member for member in members if PurePosixPath(member.name).name == "pyproject.toml"
        ]
        if len(pyprojects) != 1:
            raise RuntimeError(f"{artifact.project.name}: sdist must contain one pyproject.toml")
        member = pyprojects[0]
        extracted = archive.extractfile(member)
        if extracted is None:
            raise RuntimeError(f"{artifact.project.name}: cannot read sdist pyproject")
        data = tomllib.loads(extracted.read().decode("utf-8"))
        if str(data["project"]["version"]) != VERSION:
            raise RuntimeError(f"{artifact.project.name}: sdist version mismatch")


def inspect_artifacts(artifacts: tuple[Artifact, ...]) -> None:
    for artifact in artifacts:
        inspect_wheel(artifact)
        inspect_sdist(artifact)
        print(f"checked {artifact.project.name} {VERSION}")


def _venv_python(venv: Path) -> Path:
    windows = venv / "Scripts" / "python.exe"
    return windows if windows.exists() else venv / "bin" / "python"


def _venv_rakit(venv: Path) -> Path:
    windows = venv / "Scripts" / "rakit.exe"
    return windows if windows.exists() else venv / "bin" / "rakit"


def _clean_env() -> dict[str, str]:
    env = os.environ.copy()
    env.pop("PYTHONPATH", None)
    env["PYTHONNOUSERSITE"] = "1"
    return env


def _assert_installed_imports(python: Path, *, cwd: Path, repository: Path) -> None:
    modules = repr(_STANDARD_MODULES)
    repository_text = repr(str(repository.resolve()))
    code = f"""
import importlib
from pathlib import Path
modules = {modules}
repo = Path({repository_text}).resolve()
for name in modules:
    module = importlib.import_module(name)
    file = getattr(module, '__file__', None)
    if file is None:
        continue
    path = Path(file).resolve()
    if repo == path or repo in path.parents:
        raise SystemExit(f'working-tree import leaked for {{name}}: {{path}}')
    print(name, path)
"""
    _run([str(python), "-I", "-c", code], cwd=cwd, env=_clean_env())


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _wait_for_port(port: int, process: subprocess.Popen[str], timeout: float = 20.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if process.poll() is not None:
            stdout, stderr = process.communicate(timeout=1)
            raise RuntimeError(
                f"installed minimal example exited early ({process.returncode})\n{stdout}\n{stderr}"
            )
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.25):
                return
        except OSError:
            time.sleep(0.1)
    raise RuntimeError("timed out waiting for installed minimal example")


def clean_install_smoke(dist: Path, root: Path, workspace: Path) -> None:
    venv = workspace / "venv"
    _run(["uv", "venv", str(venv), "--python", sys.executable], cwd=workspace)
    python = _venv_python(venv)
    _run(
        [
            "uv",
            "pip",
            "install",
            "--python",
            str(python),
            "--find-links",
            str(dist),
            f"rakit[standard]=={VERSION}",
        ],
        cwd=workspace,
        env=_clean_env(),
    )
    cli = _venv_rakit(venv)
    _assert_installed_imports(python, cwd=workspace, repository=root)
    _run([str(cli), "--help"], cwd=workspace, env=_clean_env())

    # Copy the actual official minimal example into a directory outside the repository. The only
    # Python packages visible to it are the clean environment and its own source tree.
    example_root = workspace / "installed-example"
    destination = example_root / "examples" / "minimal"
    destination.mkdir(parents=True)
    (example_root / "examples" / "__init__.py").write_text("", encoding="utf-8")
    shutil.copy2(root / "examples" / "minimal" / "main.py", destination / "main.py")
    (destination / "__init__.py").write_text("", encoding="utf-8")

    _run(
        [str(cli), "check", "examples.minimal.main:admin"],
        cwd=example_root,
        env=_clean_env(),
    )

    port = _free_port()
    command = [
        str(cli),
        "run",
        "examples.minimal.main:admin",
        "--server",
        "uvicorn",
        "--host",
        "127.0.0.1",
        "--port",
        str(port),
    ]
    print("+", " ".join(command), flush=True)
    process = subprocess.Popen(
        command,
        cwd=example_root,
        env=_clean_env(),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    try:
        _wait_for_port(port, process)
    finally:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)


def check_standard_extra(root: Path) -> None:
    data = tomllib.loads(
        (root / "packages" / "rakit" / "pyproject.toml").read_text(encoding="utf-8")
    )
    standard = tuple(data["project"]["optional-dependencies"].get("standard", ()))
    required = {
        f"rakit-sqlalchemy=={VERSION}",
        f"rakit-auth-sqlalchemy=={VERSION}",
        f"rakit-storage-local=={VERSION}",
        f"rakit-server-uvicorn=={VERSION}",
    }
    missing = required - set(standard)
    if missing:
        raise RuntimeError(f"rakit[standard] missing official capabilities: {sorted(missing)}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--skip-install",
        action="store_true",
        help="build/inspect artifacts but skip the clean installed-runtime smoke",
    )
    args = parser.parse_args()

    root = repository_root()
    projects = discover_projects(root)
    print("official distributions:", ", ".join(project.name for project in projects))
    check_standard_extra(root)

    with tempfile.TemporaryDirectory(prefix="rakit-artifacts-") as temporary:
        workspace = Path(temporary)
        dist = workspace / "dist"
        artifacts = build_projects(projects, dist, root)
        inspect_artifacts(artifacts)
        if not args.skip_install:
            clean_install_smoke(dist, root, workspace)

    print(f"artifact gate passed for {len(projects)} official distributions at {VERSION}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
