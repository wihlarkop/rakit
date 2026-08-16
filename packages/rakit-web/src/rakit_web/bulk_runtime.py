"""Compatibility imports for the canonical bulk route runtime."""

from rakit_core.idempotency import OperationReceipt
from starlette.requests import Request
from starlette.responses import Response

from .bulk_routes import BulkActionBinding, build_bulk_action_routes
from .bulk_routes import _completed_response as _semantic_completed_response


def _completed_response(
    request: Request,
    receipt: OperationReceipt | None,
    fallback: str | None = None,
) -> Response:
    """Compatibility wrapper; completed receipts own their validated redirect."""

    del fallback
    return _semantic_completed_response(request, receipt)


__all__ = ["BulkActionBinding", "build_bulk_action_routes"]
