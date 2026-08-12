"""Translate semantic mutation success to HTTP/HTMX responses."""

import json
from dataclasses import dataclass

from starlette.requests import Request
from starlette.responses import RedirectResponse, Response


@dataclass(frozen=True)
class MutationPresentationResult:
    location: str
    refresh_targets: tuple[str, ...] = ()
    message: str | None = None


def mutation_success(
    request: Request,
    *,
    location: str,
    refresh_targets: tuple[str, ...] = (),
    message: str | None = None,
) -> Response:
    if request.headers.get("HX-Request") == "true":
        if refresh_targets or message:
            trigger: dict[str, object] = {}
            if refresh_targets:
                trigger["rakit:refresh"] = {"targets": list(refresh_targets)}
            if message:
                trigger["rakit:toast"] = {"message": message}
            return Response(
                status_code=204,
                headers={"HX-Trigger": json.dumps(trigger), "Cache-Control": "no-store"},
            )
        return Response(
            status_code=204,
            headers={"HX-Redirect": location, "Cache-Control": "no-store"},
        )
    return RedirectResponse(location, status_code=303, headers={"Cache-Control": "no-store"})
