"""Translate a successful mutation to HTMX or full-page navigation."""

from starlette.requests import Request
from starlette.responses import RedirectResponse, Response


def mutation_success(request: Request, *, location: str) -> Response:
    if request.headers.get("HX-Request") == "true":
        return Response(
            status_code=204,
            headers={"HX-Redirect": location, "Cache-Control": "no-store"},
        )
    return RedirectResponse(location, status_code=303, headers={"Cache-Control": "no-store"})
