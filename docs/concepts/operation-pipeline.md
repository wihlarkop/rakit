# Operation Pipeline

Mutating framework operations converge on `OperationPlan` and `OperationContext`.

A request boundary first resolves the principal, validates route-specific input, checks CSRF or
other request guards, and constructs an explicit authorization capability. The resulting operation
plan records the operation kind, target, mutating flag, transaction policy, concurrency/confirmation
requirements, idempotency fingerprint, executor capabilities, and success classification.

Before application code executes Rakit verifies that the authorization capability matches the
active operation context. Managed `AUTO`/`MANUAL` mutations require an executor that participates in
the root unit of work; strong concurrency requires an atomic executor capability. Deadlines and
cooperative cancellation checkpoints are carried in the operation context.

`AUTO` marks the root unit of work successful only when the semantic result is successful. Rejected
or validation results therefore roll back rather than being treated as transport-level success.
Post-commit work is deliberately separate from the durable database decision.
