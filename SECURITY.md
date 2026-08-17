# Security Policy

## Supported versions

Rakit is currently pre-1.0. Security fixes are provided for the latest published alpha line unless a
release announcement explicitly states a wider support window. Before the first public tag, the
current default branch is the security-fix target.

## Reporting a vulnerability

Please do **not** open a public GitHub issue, discussion, or pull request containing an undisclosed
security vulnerability.

Use GitHub Private Vulnerability Reporting for this repository when it is enabled. If that feature is
not available, contact the maintainers through a private GitHub-supported channel and provide only
enough public information to establish a private contact path. This project does not publish a
personal maintainer email address for vulnerability intake.

A useful report includes:

- affected Rakit package/version or commit;
- minimal reproduction steps;
- expected and observed security impact;
- whether authentication/authorization is required;
- relevant deployment assumptions;
- any proposed mitigation, if known.

Please allow maintainers time to reproduce, assess, patch, and coordinate disclosure before making
the issue public.

## Production security checklist

Before exposing Rakit to untrusted traffic:

- run a supported Python version and current Rakit security release;
- keep debug disabled;
- use persistent high-entropy signing keys and maintain a rotation plan;
- configure exact trusted hosts and only the proxy networks you operate;
- terminate TLS correctly and keep browser session cookies secure;
- use production-safe persistent/shared session, idempotency, and rate-limit stores where required;
- keep CSP and CSRF protections enabled;
- run database migrations before accepting traffic and never rewrite a migration already published;
- constrain file extensions, MIME types, sizes, storage roots, and private-download permissions;
- add malware/quarantine processing if the application's upload threat model requires it;
- expose health/readiness only as intended by the deployment and stop routing traffic when readiness
  falls during shutdown;
- review custom templates, plugins, adapters, handlers, and external service integrations separately;
- run the release security regression suite and artifact checks before deployment.

## Security boundaries

Rakit validates framework-owned composition, request security, permission checks, operation
capabilities, token handling, and the built-in local-storage boundary. It cannot guarantee security
properties claimed incorrectly by a custom adapter or application code that bypasses documented
operation/storage/auth contracts.
