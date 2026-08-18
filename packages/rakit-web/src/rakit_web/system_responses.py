"""Safe HTML/JSON responses for framework-owned system surfaces."""

from dataclasses import dataclass

from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.templating import Jinja2Templates

from .auth_state import AuthReason

_REASON_MESSAGES: dict[AuthReason, tuple[str, str]] = {
    AuthReason.SESSION_EXPIRED: (
        "warning",
        "Your session has expired. Sign in again to continue.",
    ),
    AuthReason.SIGNED_OUT: ("success", "You have signed out successfully."),
}


def auth_reason_message(raw_reason: str | None) -> tuple[str, str] | None:
    """Resolve only the fixed authentication reason whitelist."""

    if raw_reason is None:
        return None
    try:
        reason = AuthReason(raw_reason)
    except ValueError:
        return None
    return _REASON_MESSAGES[reason]


@dataclass(frozen=True, slots=True)
class SystemPageRenderer:
    """Render fixed browser system pages without exception internals."""

    templates: Jinja2Templates
    label: str

    def _response(
        self,
        request: Request,
        *,
        template: str,
        status_code: int,
        title: str,
        message: str,
        dashboard_url: str | None = None,
        request_id: str | None = None,
    ) -> Response:
        return self.templates.TemplateResponse(
            request,
            template,
            {
                "label": self.label,
                "system_title": title,
                "system_message": message,
                "dashboard_url": dashboard_url,
                "request_id": request_id,
                "rakit_shell_enabled": False,
                "rakit_shell_mode": "system",
            },
            status_code=status_code,
            headers={"Cache-Control": "no-store"},
        )

    def forbidden(self, request: Request, *, dashboard_url: str | None = None) -> Response:
        return self._response(
            request,
            template="system/403.html",
            status_code=403,
            title="Access denied",
            message="You don't have permission to view this page.",
            dashboard_url=dashboard_url,
        )

    def not_found(self, request: Request, *, dashboard_url: str | None = None) -> Response:
        return self._response(
            request,
            template="system/404.html",
            status_code=404,
            title="Page not found",
            message="The page you're looking for doesn't exist or may have been moved.",
            dashboard_url=dashboard_url,
        )

    def internal_error(self, request: Request, *, dashboard_url: str | None = None) -> Response:
        raw_request_id = request.scope.get("state", {}).get("request_id")
        request_id = raw_request_id if isinstance(raw_request_id, str) and raw_request_id else None
        return self._response(
            request,
            template="system/500.html",
            status_code=500,
            title="Something went wrong",
            message="We couldn't complete this request.",
            dashboard_url=dashboard_url,
            request_id=request_id,
        )


def unexpected_api_error(request: Request) -> JSONResponse:
    """Return a stable production JSON 500 without exception details."""

    raw_request_id = request.scope.get("state", {}).get("request_id")
    request_id = raw_request_id if isinstance(raw_request_id, str) else ""
    return JSONResponse(
        {
            "error": {"code": "internal.error", "message": "Internal server error."},
            "request_id": request_id,
        },
        status_code=500,
        headers={"Cache-Control": "no-store"},
    )


__all__ = ["SystemPageRenderer", "auth_reason_message", "unexpected_api_error"]
