from __future__ import annotations

from pathlib import Path


def patch_package_count_test() -> None:
    path = Path("tests/examples/test_read_examples.py")
    text = path.read_text()
    text = text.replace(
        "def test_all_packages_builds_exactly_the_ten_official_distributions(",
        "def test_all_packages_builds_exactly_the_twelve_official_distributions(",
    )
    old = '        "rakit_core",\n        "rakit_server",'
    new = (
        '        "rakit_core",\n'
        '        "rakit_schema_msgspec",\n'
        '        "rakit_schema_pydantic",\n'
        '        "rakit_server",'
    )
    if "rakit_schema_msgspec" not in text:
        if old not in text:
            raise SystemExit("official distribution expectation marker missing")
        text = text.replace(old, new, 1)
    path.write_text(text)


def patch_roadmap() -> None:
    path = Path("docs/roadmap.md")
    text = path.read_text()
    text = text.replace(
        "| Phase C4 capability discovery | **Next** |\n"
        "| Phase C developer experience and lifecycle ergonomics | **Next** |\n"
        "| Phase D adapter ecosystem | **Planned** |",
        "| Phase C4 capability discovery | **Complete** |\n"
        "| **Phase C overall** | **Complete** |\n"
        "| Phase D1 adapter contract hardening | **Complete** |\n"
        "| Phase D2 schema adapter ecosystem | **Complete** |\n"
        "| Phase D3 persistence adapter ecosystem | **Next** |\n"
        "| Phase D adapter ecosystem | **Next** |",
    )
    text = text.replace(
        "## Phase C — Developer experience and lifecycle ergonomics\n\n**Status: Next**",
        "## Phase C — Developer experience and lifecycle ergonomics\n\n**Status: Complete**",
    )

    c4_start = text.index("### C4 — Capability discovery")
    d_start = text.index("## Phase D — Adapter ecosystem")
    c4 = """### C4 — Capability discovery

**Status: Complete**

C4 established first-party capability discovery as a stable diagnostic surface:

- canonical capability identifiers and provider metadata;
- installed integration inventory through `rakit.integrations` entry points;
- configured-versus-installed integration reporting;
- `rakit capabilities` human and JSON output;
- aggregate `rakit check` capability diagnostics;
- server, schema, persistence, authentication, and storage metadata;
- fail-closed duplicate integration identifiers and actionable configuration diagnostics.

C4 closed with canonical CI and became the discovery foundation used by Phase D adapter work.

"""
    text = text[:c4_start] + c4 + text[d_start:]

    d_start = text.index("## Phase D — Adapter ecosystem")
    e_start = text.index("## Phase E — Generated APIs v1")
    phase_d = """## Phase D — Adapter ecosystem

**Status: Next**

Phase D proves that Rakit's capability architecture works across multiple concrete implementations. New adapters are added deliberately and must advertise only behavior they can prove against canonical contracts.

### D1 — Adapter Contract Hardening

**Status: Complete**

- versioned canonical capability contracts;
- hard prerequisite validation and fail-closed conformance;
- deterministic maintainer conformance matrix;
- behavioral proof coverage for first-party SQLAlchemy, Pydantic, and Starlette integrations;
- C4 compatibility gate for capability discovery metadata.

### D2 — Schema Adapter Ecosystem

**Status: Complete**

- extracted Pydantic ownership from `rakit-web` into `rakit-schema-pydantic`;
- added `rakit-schema-msgspec` as a peer first-party schema integration;
- retained Pydantic as the deterministic default experience without concrete schema coupling in `rakit-core` or `rakit-web`;
- added explicit runtime schema selection and actionable invalid-selection diagnostics;
- proved both Pydantic and msgspec against all four `schema.*@1` contracts;
- locked presence-aware partial-update semantics where missing differs from explicit `None`;
- added package/discovery metadata, install UX, artifact verification, and cross-adapter regression coverage.

### D3 — Persistence Adapter Ecosystem

**Status: Next**

Add a second persistence implementation and use it to pressure-test data-source, write-service, transaction, pagination, relationship, and generated-operation contracts without importing ORM-specific semantics into core.

### D4 — Web Framework Integrations

**Status: Planned**

#### D4.0 — Web Integration Contract

Define the framework-integration boundary and acceptance matrix before adding more host frameworks.

#### D4.1 — Litestar

Add first-class Litestar integration against the D4.0 contract.

#### D4.2 — FastAPI

Promote FastAPI mounting/composition from guidance into a first-class integration where that adds real value beyond Starlette compatibility.

#### D4.3 — Starlette

Harden and document Starlette as the canonical ASGI/reference integration under the shared web contract.

#### D4.4 — Flask

Explore and implement an honest Flask integration without pretending WSGI and ASGI semantics are identical.

#### D4.5 — Sanic

Add Sanic integration if the D4 contract maps cleanly to its runtime model.

#### D4.6 — Integration DX & Compatibility Matrix

Unify install guidance, discovery, conformance, examples, and supported-version policy across first-party web integrations.

### D5 — Adapter Authoring DX / SDK

**Status: Planned**

Turn the internal conformance machinery proven by D1-D4 into a supported authoring experience for third-party adapter maintainers, without exposing unstable internals prematurely.

### D6 — Additional First-party Adapters

**Status: Planned**

Add further schema, persistence, storage, authentication, or transport adapters only where ecosystem demand and the capability model justify first-party ownership.

"""
    text = text[:d_start] + phase_d + text[e_start:]
    path.write_text(text)


def patch_artifact_smoke() -> None:
    path = Path("scripts/check_artifacts.py")
    text = path.read_text()
    text = text.replace(
        '    "rakit_web",\n    "rakit_sqlalchemy",',
        '    "rakit_web",\n    "rakit_schema_pydantic",\n    "rakit_sqlalchemy",',
    )
    text = text.replace(
        '_GRANIAN_MODULES = (\n    "rakit.server.granian",\n    "rakit_server_granian",\n)\n',
        '_GRANIAN_MODULES = (\n    "rakit.server.granian",\n    "rakit_server_granian",\n)\n'
        '_MSGSPEC_MODULES = ("rakit_schema_msgspec",)\n',
    )
    if "_MSGSPEC_MODULES" not in text:
        raise SystemExit("msgspec artifact module declaration patch failed")

    marker = """    _assert_installed_imports(
        python,
        modules=_GRANIAN_MODULES,
        cwd=workspace,
        repository=root,
    )
"""
    if '_install_extra(dist, python, workspace, "msgspec")' not in text:
        if marker not in text:
            raise SystemExit("artifact smoke insertion marker missing")
        addition = marker + """
    # msgspec is optional: prove its root convenience extra resolves from the
    # locally built artifacts without changing the default Pydantic selection.
    _install_extra(dist, python, workspace, "msgspec")
    _assert_installed_imports(
        python,
        modules=_MSGSPEC_MODULES,
        cwd=workspace,
        repository=root,
    )
"""
        text = text.replace(marker, addition, 1)
    path.write_text(text)


def main() -> None:
    patch_package_count_test()
    patch_roadmap()
    patch_artifact_smoke()


if __name__ == "__main__":
    main()
