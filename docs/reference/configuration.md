# Configuration

`Admin(...)` is the normal configuration entry point. Core configuration types are also public from
`rakit.core` for integrations that need typed configuration objects.

Important Admin options include:

- `admin_id` and `title`;
- `debug`;
- `secret_key`;
- `template_dirs`;
- `auth_backend` and `session_store` (supplied together);
- `login_rate_limiter`;
- `allowed_hosts` and `trusted_proxies`;
- `content_security_policy_enabled`;
- `superuser_bypass`;
- `mutation_deadline_seconds`;
- `event_bus`;
- `operation_idempotency_store`;
- optional advanced action response and schema adapters.

Production validation rejects weak/missing security configuration and deployment-only combinations
that cannot provide their claimed safety. `SecretValue` redacts its value from normal string/repr
boundaries; treat the underlying secret as a credential regardless.

`SecurityConfig`, `LifecycleConfig`, and `RakitConfig` are portable core types. Prefer passing normal
Admin options unless you are building framework infrastructure around Rakit.
