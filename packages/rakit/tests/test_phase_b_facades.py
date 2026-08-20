def test_domain_action_composition_is_available_from_root_facade() -> None:
    from rakit import ActionContext, ActionExecutor, DomainActionExecutor, TransactionPolicy
    from rakit_core.actions import (
        ActionContext as CoreActionContext,
    )
    from rakit_core.actions import (
        ActionExecutor as CoreActionExecutor,
    )
    from rakit_core.actions import (
        DomainActionExecutor as CoreDomainActionExecutor,
    )
    from rakit_core.transactions import TransactionPolicy as CoreTransactionPolicy

    assert ActionContext is CoreActionContext
    assert ActionExecutor is CoreActionExecutor
    assert DomainActionExecutor is CoreDomainActionExecutor
    assert TransactionPolicy is CoreTransactionPolicy


def test_operational_sqlalchemy_auth_surface_is_available_from_facade() -> None:
    from rakit.auth.sqlalchemy import (
        Argon2PasswordHasher,
        AuthBase,
        Permission,
        Role,
        SQLAlchemyAuthPlugin,
        SQLAlchemyIdempotencyStore,
        User,
        sync_permissions,
    )
    from rakit_auth_sqlalchemy.idempotency import SQLAlchemyIdempotencyStore as ConcreteStore
    from rakit_auth_sqlalchemy.models import Base
    from rakit_auth_sqlalchemy.models import Permission as ConcretePermission
    from rakit_auth_sqlalchemy.models import Role as ConcreteRole
    from rakit_auth_sqlalchemy.models import User as ConcreteUser
    from rakit_auth_sqlalchemy.passwords import Argon2PasswordHasher as ConcreteHasher
    from rakit_auth_sqlalchemy.plugin import SQLAlchemyAuthPlugin as ConcretePlugin
    from rakit_auth_sqlalchemy.rbac import sync_permissions as concrete_sync_permissions

    assert Argon2PasswordHasher is ConcreteHasher
    assert AuthBase is Base
    assert Permission is ConcretePermission
    assert Role is ConcreteRole
    assert SQLAlchemyAuthPlugin is ConcretePlugin
    assert SQLAlchemyIdempotencyStore is ConcreteStore
    assert User is ConcreteUser
    assert sync_permissions is concrete_sync_permissions
