# Events Reference

The public event primitives are available from `rakit.core`:

```python
from rakit.core import DomainEvent, EventBus, EventPublisher
```

`EventBus` is application-scoped. `EventPublisher` is normally resolved in an operation scope and
carries publication through the same operation context used by mutations/actions/pages/endpoints.

Only event names and payload shapes explicitly documented as public carry compatibility guarantees.
Application-specific events belong to the application. Undocumented framework-internal events are
internal implementation details.
