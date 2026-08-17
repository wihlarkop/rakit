# Dependency Injection and Transactions

Rakit's service registry has explicit application, request, and operation scopes. Plugins register
values/factories during compilation; request handling opens child scopes and operation handlers can
resolve operation-local services through `OperationContext.services`.

Application scope is appropriate for long-lived shared objects. Request scope follows one incoming
request. Operation scope follows one logical mutation/action/page/endpoint execution and is the
boundary used for operation-local publishers and persistence services.

Transactions are declared with `TransactionPolicy`:

- `READ_ONLY` does not open a write unit of work;
- `AUTO` lets Rakit commit a successful semantic result and roll back failures/rejections;
- `MANUAL` exposes a root unit of work but never auto-commits;
- `DISABLED` explicitly opts out of Rakit-managed atomicity for an unmanaged side effect.

An adapter claiming managed transactions must register an `OperationUnitOfWorkFactory`, and an
executor must truthfully advertise unit-of-work participation. Rakit rejects combinations it cannot
prove rather than silently opening independent nested transactions.
