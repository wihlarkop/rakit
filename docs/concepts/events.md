# Events

`EventBus` is the application-scoped in-process event dispatcher and `EventPublisher` is the
operation-facing publication service. Application code and adapters should depend on these portable
contracts rather than a web framework request object.

Events use `DomainEvent` payloads. Publication belongs to the operation lifecycle: transaction-aware
adapters can defer externally visible publication until the durable transaction outcome is known.
Application code should not describe an event as durable merely because a handler ran before the
root unit of work committed.

Event payload compatibility is part of the public compatibility policy when an event is explicitly
documented as public. Internal implementation events may change without a compatibility promise.
