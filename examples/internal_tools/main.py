"""Internal-tool composition: page, action, service injection, and endpoint."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from rakit import (
    ActionDefinition,
    ActionScope,
    ActionSuccess,
    Admin,
    EndpointAccessPolicy,
    EndpointResult,
    PageDefinition,
    PageResult,
    SecretValue,
)
from rakit.core import (
    IdempotencyReservation,
    IdempotencyStatus,
    OperationReceipt,
    Principal,
    ServiceScope,
    SessionRecord,
)


class ReportService:
    def __init__(self) -> None:
        self.refreshes = 0

    def snapshot(self) -> dict[str, object]:
        return {"status": "healthy", "refreshes": self.refreshes}

    def refresh(self) -> None:
        self.refreshes += 1


class RefreshReport:
    """Action executor with explicit constructor injection."""

    def __init__(self, reports: ReportService) -> None:
        self.reports = reports

    async def execute(self, _context: object) -> ActionSuccess[dict[str, object]]:
        self.reports.refresh()
        return ActionSuccess(payload=self.reports.snapshot(), message="Report refreshed")


class DemoAuthBackend:
    async def authenticate(self, identifier: str, password: str) -> Principal | None:
        if (identifier.strip().lower(), password) != ("operator@example.com", "demo-password"):
            return None
        return self._principal()

    async def resolve_principal(self, subject_id: str) -> Principal | None:
        return self._principal() if subject_id == "internal-operator" else None

    @staticmethod
    def _principal() -> Principal:
        return Principal(
            subject_id="internal-operator",
            authenticated=True,
            display_name="Internal Operator",
            is_superuser=True,
        )


class DemoSessionStore:
    production_safe = False

    def __init__(self) -> None:
        self.record: SessionRecord | None = None
        self.token = "internal-demo-token"
        self.counter = 0

    async def create(self, principal: Principal) -> tuple[str, SessionRecord]:
        assert principal.subject_id is not None
        self.counter += 1
        now = datetime.now(UTC)
        self.token = f"internal-demo-token-{self.counter}"
        self.record = SessionRecord(
            session_id=f"internal-session-{self.counter}",
            subject_id=principal.subject_id,
            created_at=now,
            last_seen_at=now,
            idle_expires_at=now + timedelta(hours=1),
            absolute_expires_at=now + timedelta(hours=8),
        )
        return self.token, self.record

    async def resolve(self, raw_token: str) -> SessionRecord | None:
        return self.record if raw_token == self.token else None

    async def rotate(self, session_id: str) -> tuple[str, SessionRecord]:
        if self.record is None or self.record.session_id != session_id:
            raise KeyError(session_id)
        principal = Principal(subject_id=self.record.subject_id, authenticated=True)
        return await self.create(principal)

    async def revoke(self, session_id: str) -> None:
        if self.record is not None and self.record.session_id == session_id:
            self.record = None


class DemoIdempotencyStore:
    """Single-process action store for this development-only example."""

    production_safe = False

    async def begin(self, token_hash: str, *, fingerprint: str) -> IdempotencyReservation:
        del token_hash, fingerprint
        return IdempotencyReservation(1, IdempotencyStatus.IN_PROGRESS)

    async def complete(
        self,
        reservation: IdempotencyReservation,
        receipt: OperationReceipt,
    ) -> None:
        del reservation, receipt

    async def release(self, reservation: IdempotencyReservation) -> None:
        del reservation

    async def fail_final(self, reservation: IdempotencyReservation) -> None:
        del reservation


reports = ReportService()
admin = Admin(
    admin_id="internal_tools",
    title="Internal tools",
    debug=True,
    secret_key=SecretValue("development-only-internal-tools-key"),
    auth_backend=DemoAuthBackend(),
    session_store=DemoSessionStore(),
    operation_idempotency_store=DemoIdempotencyStore(),
)

# Rakit's registry owns the application-scoped service. The page and action use
# explicit constructor/closure injection, keeping their dependency obvious.
admin.builder.registry.add_value(
    ReportService,
    reports,
    scope=ServiceScope.APPLICATION,
)


def report_page(_context: object) -> PageResult[dict[str, object]]:
    return PageResult(payload=reports.snapshot(), message="Current report state")


admin.register_page(
    PageDefinition(
        page_id="report",
        path="/reports",
        label="Report",
        handler=report_page,
    ),
    actions=(
        ActionDefinition(
            action_id="refresh_report",
            label="Refresh report",
            scope=ActionScope.PAGE,
            page_id="report",
            executor=RefreshReport(reports),
        ),
    ),
)


@admin.api.get(
    "/api/report",
    endpoint_id="report_snapshot",
    access_policy=EndpointAccessPolicy.PUBLIC,
)
def report_endpoint(_context: object) -> EndpointResult[dict[str, object]]:
    return EndpointResult(reports.snapshot())


app = admin.asgi()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8000)
