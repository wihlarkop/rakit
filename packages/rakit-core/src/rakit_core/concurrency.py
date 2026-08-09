"""Signed optimistic-concurrency tokens for resource mutations."""

from datetime import timedelta
from enum import StrEnum
from typing import Any

from rakit_core.crypto import TokenService
from rakit_core.errors import ErrorCode, RakitError
from rakit_core.identity import RecordIdentity


class ConcurrencyMode(StrEnum):
    AUTO = "auto"
    REQUIRED = "required"
    DISABLED = "disabled"


class ConcurrencyTokenService:
    """Issues purpose-separated tokens bound to one identity and revision."""

    def __init__(
        self, token_service: TokenService, *, ttl: timedelta = timedelta(minutes=15)
    ) -> None:
        self._token_service = token_service
        self._ttl = ttl

    def issue(self, identity: RecordIdentity, version: Any) -> str:
        return self._token_service.issue_in(
            "concurrency",
            {"identity": dict(identity.values), "version": version},
            self._ttl,
        )

    def verify(self, token: str, identity: RecordIdentity, version: Any) -> None:
        try:
            claims = self._token_service.verify(token, expected_purpose="concurrency")
        except ValueError as exc:
            raise self._conflict() from exc
        if claims.get("identity") != dict(identity.values) or claims.get("version") != version:
            raise self._conflict()

    @staticmethod
    def _conflict() -> RakitError:
        return RakitError(
            code=ErrorCode.RESOURCE_CONFLICT,
            message="The resource has changed since this form was opened.",
            status_code=409,
        )
