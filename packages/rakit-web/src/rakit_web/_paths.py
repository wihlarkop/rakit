from starlette.requests import Request


def mounted_path(request: Request, path: str) -> str:
    """Prefix `path` with the ASGI `root_path` this request arrived under,
    so links, redirects, and cookie paths stay correct when `Admin.asgi()`
    is mounted under a prefix (e.g. `app.mount("/admin", admin.asgi())`)
    rather than served at the application root.
    """
    root_path = request.scope.get("root_path", "").rstrip("/")
    return f"{root_path}{path}"
