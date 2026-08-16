from rakit_sqlalchemy.capabilities import SQLALCHEMY_CAPABILITIES


def test_sqlalchemy_declares_persistence_transaction_and_concurrency_capabilities() -> None:
    assert SQLALCHEMY_CAPABILITIES.provider_id == "persistence.sqlalchemy"
    assert SQLALCHEMY_CAPABILITIES.capabilities.names == (
        "concurrency.atomic-optimistic",
        "persistence.read",
        "persistence.relationships",
        "persistence.write",
        "transactions.root-uow",
    )
