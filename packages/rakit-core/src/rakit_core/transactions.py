from enum import StrEnum


class TransactionPolicy(StrEnum):
    """How an operation-scoped unit of work reaches a durable outcome."""

    AUTO = "auto"
    READ_ONLY = "read_only"
    DISABLED = "disabled"
    MANUAL = "manual"
