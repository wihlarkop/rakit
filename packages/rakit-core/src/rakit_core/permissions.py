from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict, field_validator

from rakit_core.auth import Principal


class PermissionRequirement(BaseModel):
    """An allow-only permission check: either all named permissions must be
    present (`mode="all"`) or at least one must be present (`mode="any"`).
    There is no deny mode -- explicit deny is a roadmap item.

    `permissions` must be non-empty: `all(())` and `any(())` both evaluate
    to Python truthy values, so an accidentally-empty requirement would
    otherwise vacuously match every principal (including an anonymous one)
    -- fail closed by rejecting that shape at construction time instead.
    """

    model_config = ConfigDict(frozen=True)

    mode: Literal["all", "any"]
    permissions: tuple[str, ...]

    @field_validator("permissions")
    @classmethod
    def _require_at_least_one_permission(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if not value:
            raise ValueError("PermissionRequirement.permissions must not be empty")
        return value

    @classmethod
    def all_of(cls, *permissions: str) -> "PermissionRequirement":
        return cls(mode="all", permissions=permissions)

    @classmethod
    def any_of(cls, *permissions: str) -> "PermissionRequirement":
        return cls(mode="any", permissions=permissions)

    def matches(self, principal: Principal, *, superuser_bypass: bool = True) -> bool:
        # An unauthenticated principal never matches, regardless of what
        # flags it carries. Callers are expected to reject anonymous
        # requests before reaching here, but a requirement that honours
        # `is_superuser` on an unauthenticated principal would be a latent
        # privilege escalation for any caller that forgets that ordering.
        if not principal.authenticated:
            return False
        if superuser_bypass and principal.is_superuser:
            return True
        results = [permission in principal.permissions for permission in self.permissions]
        return all(results) if self.mode == "all" else any(results)


class AuthorizationDecision(BaseModel):
    """A structured authorization result -- not a bare boolean, so callers
    can log/report a stable machine-readable `code` and an optional
    developer-safe `reason` without inventing their own error shape."""

    model_config = ConfigDict(frozen=True)

    allowed: bool
    code: str
    reason: str | None = None


class AuthorizationPolicy(Protocol):
    """Evaluates a `PermissionRequirement` against a `Principal`, returning
    a structured decision. Operation permission (this) and record-level
    visibility are separate boundaries -- this protocol only answers "may
    this principal perform this operation," never "which records."""

    async def authorize(
        self, principal: Principal, requirement: PermissionRequirement
    ) -> AuthorizationDecision: ...
