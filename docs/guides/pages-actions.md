# Pages and Actions

Pages and actions are application operations compiled into the same permission and execution graph
as resources.

## Pages

Register a `PageDefinition` with `admin.register_page()`. Read-only pages may use a
`DomainPageHandler` or a compatible callable and return `PageResult`, `PageRedirect`, or
`PageRejected`. Mutating pages are POST/Redirect/GET operations and require explicit idempotency,
CSRF, and a transaction-aware handler when using managed transactions.

## Actions

`ActionDefinition` supports PAGE, RESOURCE, RECORD, and BULK scopes. Availability is presentation
policy; authorization is a separate permission decision. The POST path always re-checks both
against current state.

Structured results include success, redirect, refresh, rendered fragment, rejection, and validation
outcomes. Record actions may opt into optimistic concurrency only when the selected executor can
truthfully provide the required atomic unit-of-work semantics.

Actions can request a form, preview, and signed confirmation. Confirmation never replaces
authorization: the final POST still checks the current principal and target.

See `examples/internal_tools` for a page plus page action, and the SQLAlchemy integration tests for
transactional record actions.
