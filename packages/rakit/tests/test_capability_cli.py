import json

import pytest
from click.testing import CliRunner
from rakit.cli import cli
from rakit_core.capabilities import (
    CapabilityProvider,
    CapabilityRequirement,
    CapabilitySet,
    analyze_capabilities,
)
from rakit_core.compiler import CapabilityConfigurationError, CompiledApplication
from rakit_core.integrations import ConfiguredIntegration, IntegrationDescriptor


class CompilesSuccessfully:
    def compile(self) -> CompiledApplication:
        schema = CapabilityProvider(
            provider_id="schema.pydantic",
            capabilities=CapabilitySet.of(
                "schema.input-validation",
                "schema.output-serialization",
            ),
        )
        web = CapabilityProvider(
            provider_id="web.starlette",
            capabilities=CapabilitySet.of("web.asgi", "web.http-routing"),
        )
        requirement = CapabilityRequirement.of(
            "generated-api.input",
            "schema.input-validation",
            "web.http-routing",
        )
        analysis = analyze_capabilities((requirement,), (web, schema))
        return CompiledApplication(
            routes=(),
            plugins=("example",),
            resources=(),
            capability_providers=analysis.providers,
            capability_requirements=analysis.requirements,
            capability_reports=analysis.reports,
            configured_integrations=(
                ConfiguredIntegration("schema.pydantic", "schema", "Pydantic"),
                ConfiguredIntegration("web.starlette", "web", "Starlette"),
            ),
            capability_analysis=analysis,
        )


class CompilesWithoutCapabilityMetadata:
    def compile(self) -> CompiledApplication:
        return CompiledApplication(routes=(), plugins=(), resources=())


class MissingCapabilities:
    def compile(self) -> CompiledApplication:
        schema = CapabilityProvider(
            provider_id="schema.pydantic",
            capabilities=CapabilitySet.of("schema.input-validation"),
        )
        analysis = analyze_capabilities(
            (
                CapabilityRequirement.of(
                    "generated-api.write",
                    "transactions.root-uow",
                ),
                CapabilityRequirement.of(
                    "generated-api.patch",
                    "schema.input-validation",
                    "schema.partial-update",
                ),
            ),
            (schema,),
        )
        raise CapabilityConfigurationError(
            analysis=analysis,
            configured_integrations=(
                ConfiguredIntegration("schema.pydantic", "schema", "Pydantic"),
            ),
        )


def _installed_integrations() -> tuple[IntegrationDescriptor, ...]:
    return (
        IntegrationDescriptor(
            "server.uvicorn",
            "server",
            "Uvicorn",
            CapabilitySet.of("server.reload"),
        ),
        IntegrationDescriptor("schema.pydantic", "schema", "Pydantic"),
    )


def test_check_prints_sorted_provider_and_requirement_diagnostics(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("rakit.cli.load_object", lambda target: CompilesSuccessfully())

    result = CliRunner().invoke(cli, ["check", "example:admin"])

    assert result.exit_code == 0
    assert result.output == (
        "Rakit configuration is valid.\n"
        "Routes: 0\n"
        "Plugins: 1\n"
        "Capability providers:\n"
        "  schema.pydantic: schema.input-validation, schema.output-serialization\n"
        "  web.starlette: web.asgi, web.http-routing\n"
        "Capability requirements:\n"
        "  generated-api.input: satisfied\n"
    )


def test_check_handles_apps_without_capability_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("rakit.cli.load_object", lambda target: CompilesWithoutCapabilityMetadata())

    result = CliRunner().invoke(cli, ["check", "example:admin"])

    assert result.exit_code == 0
    assert "Capability providers: none\n" in result.output
    assert "Capability requirements: none\n" in result.output


def test_check_explains_every_missing_capability_requirement(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("rakit.cli.load_object", lambda target: MissingCapabilities())

    result = CliRunner().invoke(cli, ["check", "example:admin"])

    assert result.exit_code == 1
    assert "Rakit configuration is invalid." in result.output
    assert "Missing capability requirements:" in result.output
    assert "generated-api.patch" in result.output
    assert "missing: schema.partial-update" in result.output
    assert "generated-api.write" in result.output
    assert "missing: transactions.root-uow" in result.output
    assert "Required adapter capabilities are not available." in result.output


def test_capabilities_json_keeps_configured_and_installed_views_separate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("rakit.cli.load_object", lambda target: CompilesSuccessfully())
    monkeypatch.setattr(
        "rakit.cli.discover_installed_integrations",
        _installed_integrations,
    )

    result = CliRunner().invoke(
        cli,
        ["capabilities", "example:admin", "--installed", "--json"],
    )

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["schema_version"] == 1
    assert payload["target"] == "example:admin"
    assert payload["valid"] is True
    assert [item["id"] for item in payload["configured"]["integrations"]] == [
        "schema.pydantic",
        "web.starlette",
    ]
    assert [item["id"] for item in payload["installed"]] == [
        "schema.pydantic",
        "server.uvicorn",
    ]
    assert payload["installed"][1]["advertised_capabilities"] == ["server.reload"]


def test_capabilities_installed_only_has_no_configured_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "rakit.cli.discover_installed_integrations",
        _installed_integrations,
    )

    result = CliRunner().invoke(cli, ["capabilities", "--installed", "--json"])

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload == {
        "schema_version": 1,
        "target": None,
        "valid": None,
        "configured": None,
        "installed": [
            {
                "id": "schema.pydantic",
                "category": "schema",
                "display_name": "Pydantic",
                "advertised_capabilities": [],
            },
            {
                "id": "server.uvicorn",
                "category": "server",
                "display_name": "Uvicorn",
                "advertised_capabilities": ["server.reload"],
            },
        ],
    }


def test_capabilities_invalid_target_still_returns_aggregate_diagnostics(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("rakit.cli.load_object", lambda target: MissingCapabilities())

    result = CliRunner().invoke(cli, ["capabilities", "example:admin", "--json"])

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["valid"] is False
    assert [
        item["id"] for item in payload["configured"]["requirements"] if item["status"] == "missing"
    ] == ["generated-api.patch", "generated-api.write"]
    assert payload["installed"] is None


def test_capabilities_requires_target_or_installed_flag() -> None:
    result = CliRunner().invoke(cli, ["capabilities"])

    assert result.exit_code == 2
    assert "Provide TARGET or use --installed." in result.output
