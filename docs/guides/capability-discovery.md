# Capability Discovery

Rakit exposes capability diagnostics without treating package installation as application configuration.
The distinction is deliberate:

- **Configured integrations** are integrations the application target actually wires into its runtime.
- **Installed integrations** are integration packages that advertise discovery metadata in the current Python environment.
- **Capability providers** are configured runtime components that provide concrete compiler capabilities.
- **Capability requirements** are the capabilities the compiled application requires.

An installed integration is not active merely because its package exists. Rakit never auto-configures an
integration from discovery metadata.

## Inspect a configured application

Use `rakit capabilities` with an application target in `module:attribute` form:

```bash
rakit capabilities myapp:admin
```

The configured view reports:

- known configured integrations such as the Starlette web runtime, Pydantic schema adapter, SQLAlchemy
  persistence, SQLAlchemy authentication, and local storage when those integrations are actually wired;
- custom schema/auth integrations as `custom/unknown` when they do not publish official Rakit identity
  metadata, rather than inventing an integration id;
- configured capability providers and the exact capabilities they provide;
- every capability requirement and whether it is satisfied or missing.

If capability requirements are missing, inspection still succeeds and reports `Status: invalid`. This is
intentional: `rakit capabilities` is an inspector, not the configuration validator.

## Inspect the installed environment

To inspect integration packages installed in the current Python environment:

```bash
rakit capabilities --installed
```

First-party C4 discovery metadata currently covers:

- `auth.sqlalchemy`
- `persistence.sqlalchemy`
- `schema.pydantic`
- `server.granian`
- `server.uvicorn`
- `storage.local`
- `web.starlette`

Installed discovery uses the `rakit.integrations` Python entry-point group. It does not scan package names,
construct runtime adapters, connect to databases, start servers, or activate plugins. Invalid descriptors,
duplicate ids, entry-point/id mismatches, and descriptor load failures fail explicitly.

Server discovery metadata is separate from the existing `rakit.servers` runtime adapter entry points.
Inspecting installed server integrations therefore does not start or configure a server.

## Compare configured and installed state

Both views can be requested together:

```bash
rakit capabilities myapp:admin --installed
```

This is useful when debugging questions such as:

- “Is SQLAlchemy installed but not configured?”
- “Which schema adapter is active in this target?”
- “Which server adapters are available in this environment?”
- “Which exact compiler requirements are still missing?”

The two sections remain separate. Presence in `Installed integrations` never causes an item to appear in
`Configured integrations`.

## Machine-readable output

Add `--json` to any capability inspection command:

```bash
rakit capabilities myapp:admin --json
rakit capabilities --installed --json
rakit capabilities myapp:admin --installed --json
```

C4 JSON output starts with `schema_version: 1`. Its top-level shape is:

```json
{
  "schema_version": 1,
  "target": "myapp:admin",
  "valid": true,
  "configured": {
    "integrations": [],
    "providers": [],
    "requirements": []
  },
  "installed": null
}
```

For installed-only inspection, `target`, `valid`, and `configured` are `null`. When `--installed` is not
requested, `installed` is `null` rather than an inferred environment view.

Arrays are emitted in deterministic order so the output is suitable for diagnostics and CI tooling.
Consumers should use `schema_version` when depending on the JSON structure.

## Validate configuration with `rakit check`

`rakit check` remains the fail-closed validator:

```bash
rakit check myapp:admin
```

A valid target exits successfully. If capability requirements are missing, Rakit evaluates the complete
requirement graph first and reports every missing requirement in one run, then exits non-zero.

Use the commands for different jobs:

| Goal | Command |
| --- | --- |
| Validate an application | `rakit check myapp:admin` |
| Inspect configured state | `rakit capabilities myapp:admin` |
| Inspect installed integrations | `rakit capabilities --installed` |
| Compare configured and installed state | `rakit capabilities myapp:admin --installed` |
| Consume structured diagnostics | add `--json` |

This separation keeps validation strict while making diagnostics complete and inspectable.
