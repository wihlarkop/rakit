# Custom Plugin

A plugin implements the compiler `Plugin` contract and registers capabilities/services/adapters in
`configure(builder)`. Plugins run during application composition, before compilation is frozen.

Use the builder's public registry/capability/adapter methods; do not mutate compiler internals.
Application-wide service values normally use `ServiceScope.APPLICATION`. Request/operation factories
should use the narrowest lifecycle they require.

A plugin id must be stable and unique within one Admin. Compilation validates plugin conflicts and
capability requirements before serving.

Keep optional integrations in their own distribution where practical. The built-in
`SQLAlchemyPlugin` and `LocalStoragePlugin` are reference examples of adapters registering only the
capabilities/services they own.
