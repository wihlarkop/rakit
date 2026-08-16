from .capabilities import Capability

WEB_ASGI = Capability("web.asgi")
WEB_HTTP_ROUTING = Capability("web.http-routing")
WEB_STREAMING_RESPONSE = Capability("web.streaming-response")

SCHEMA_FIELD_INTROSPECTION = Capability("schema.field-introspection")
SCHEMA_INPUT_VALIDATION = Capability("schema.input-validation")
SCHEMA_OUTPUT_SERIALIZATION = Capability("schema.output-serialization")
SCHEMA_PARTIAL_UPDATE = Capability("schema.partial-update")

PERSISTENCE_READ = Capability("persistence.read")
PERSISTENCE_WRITE = Capability("persistence.write")
PERSISTENCE_RELATIONSHIPS = Capability("persistence.relationships")
TRANSACTIONS_ROOT_UOW = Capability("transactions.root-uow")
CONCURRENCY_ATOMIC_OPTIMISTIC = Capability("concurrency.atomic-optimistic")

__all__ = [
    "CONCURRENCY_ATOMIC_OPTIMISTIC",
    "PERSISTENCE_READ",
    "PERSISTENCE_RELATIONSHIPS",
    "PERSISTENCE_WRITE",
    "SCHEMA_FIELD_INTROSPECTION",
    "SCHEMA_INPUT_VALIDATION",
    "SCHEMA_OUTPUT_SERIALIZATION",
    "SCHEMA_PARTIAL_UPDATE",
    "TRANSACTIONS_ROOT_UOW",
    "WEB_ASGI",
    "WEB_HTTP_ROUTING",
    "WEB_STREAMING_RESPONSE",
]
