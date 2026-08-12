"""Explicit hard-delete planning contracts."""

import secrets
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from rakit_core.identity import RecordIdentity


class DeletePolicy(StrEnum):
    HARD_DELETE = "hard_delete"


HardDeletePolicy = DeletePolicy.HARD_DELETE


@dataclass(frozen=True)
class DeletionPlan:
    identity: RecordIdentity
    expected_version: Any
    relationship_impact: tuple[str, ...] = ()
    required_permission: str = ""
    nonce: str = field(default_factory=lambda: secrets.token_urlsafe(16))
