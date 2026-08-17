# Security

Rakit treats security configuration as part of application compilation and request execution rather
than an optional deployment afterthought.

## Key rotation

Use persistent random secret material in production. `KeyRing` supports one active signing key plus
previous verification-only keys, allowing rotation without immediately invalidating still-live
signed tokens. Remove an old verification key only after every token that could have been signed by
it has expired.

## Hosts and proxies

Configure `allowed_hosts` narrowly. Do not use wildcard host trust in production. Forwarded headers
are trusted only when the immediate peer matches configured trusted proxy networks; otherwise an
attacker-controlled `X-Forwarded-*` header must not redefine request origin/security decisions.

## Cookies and CSRF

Rakit uses opaque server-side sessions. CSRF tokens are signed and bound to the resolved session.
State-changing browser routes also apply same-origin checks. Deploy behind HTTPS and keep session
cookies secure, HTTP-only where applicable, and scoped to the smallest useful path/domain.

## Upload safety

`FileField` policy validates declared filename metadata, extensions, MIME allowlists, size limits,
and storage ownership. LocalStorage generates object keys itself; the browser filename is metadata
only and never controls a filesystem path. Private access is the default. Authorization is checked
again before private-file streaming.

File type/MIME validation is not malware detection. If your threat model requires antivirus,
content disarm, media transcoding, or quarantine, add that explicitly before treating uploaded
content as trusted.

## Deployment checklist

- use persistent high-entropy signing keys and rehearse rotation;
- configure exact trusted hosts and only the proxy networks you operate;
- terminate TLS correctly and validate forwarded-header behavior;
- use persistent/shared session, idempotency, and rate-limit stores where required;
- keep CSP enabled and serve Rakit assets locally;
- keep debug disabled in production and verify error bodies do not expose tracebacks;
- constrain upload extensions, MIME types, sizes, and storage roots;
- run migrations before serving traffic;
- require `/ready` to be healthy before routing traffic and stop routing when shutdown begins;
- run the release security regression suite before deployment.

## Threat boundaries

Rakit protects framework-owned request, authorization, transaction, token, and file-storage seams.
Application-owned handlers, custom templates, custom adapters, external services, and deployment
infrastructure remain application responsibilities. A custom adapter must accurately declare its
capabilities; Rakit cannot guarantee atomicity, isolation, or security properties an adapter does
not actually implement.
