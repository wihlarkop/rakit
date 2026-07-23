import pytest
from pydantic import ValidationError
from rakit_core.auth import Principal
from rakit_core.permissions import AuthorizationDecision, PermissionRequirement


def test_all_of_and_any_of() -> None:
    principal = Principal(
        subject_id="u-1",
        authenticated=True,
        permissions=frozenset({"orders.read", "orders.approve"}),
    )
    assert PermissionRequirement.all_of("orders.read", "orders.approve").matches(principal)
    assert PermissionRequirement.any_of("orders.delete", "orders.approve").matches(principal)
    assert not PermissionRequirement.all_of("orders.read", "orders.delete").matches(principal)


def test_unauthenticated_principal_has_no_permissions_by_default() -> None:
    principal = Principal()
    assert principal.authenticated is False
    assert principal.is_superuser is False
    assert principal.permissions == frozenset()
    assert not PermissionRequirement.any_of("orders.read").matches(principal)


def test_superuser_bypasses_missing_permissions() -> None:
    principal = Principal(subject_id="u-1", authenticated=True, is_superuser=True)
    assert PermissionRequirement.all_of("orders.read", "orders.delete").matches(principal)


def test_superuser_bypass_can_be_disabled() -> None:
    principal = Principal(subject_id="u-1", authenticated=True, is_superuser=True)
    requirement = PermissionRequirement.all_of("orders.read")
    assert not requirement.matches(principal, superuser_bypass=False)


def test_any_of_with_no_matching_permission_is_rejected() -> None:
    principal = Principal(
        subject_id="u-1", authenticated=True, permissions=frozenset({"orders.read"})
    )
    assert not PermissionRequirement.any_of("orders.delete", "orders.approve").matches(principal)


def test_empty_permission_requirement_is_rejected_at_construction() -> None:
    """`all(())` and `any(())` are both truthy in Python -- an empty
    requirement must never be constructible, since it would otherwise
    vacuously match every principal, including an unauthenticated one."""
    with pytest.raises(ValidationError):
        PermissionRequirement(mode="all", permissions=())
    with pytest.raises(ValidationError):
        PermissionRequirement.any_of()


def test_authorization_decision_carries_stable_code_and_optional_reason() -> None:
    denied = AuthorizationDecision(allowed=False, code="auth.forbidden")
    allowed = AuthorizationDecision(allowed=True, code="auth.allowed", reason="superuser bypass")
    assert denied.allowed is False
    assert denied.reason is None
    assert allowed.reason == "superuser bypass"
