from rakit_server import ServerCapabilities

UVICORN_SERVER_CAPABILITIES = ServerCapabilities(
    async_serve=True,
    graceful_stop=True,
    reload=True,
    workers=True,
    app_object=True,
    import_string=True,
)

__all__ = ["UVICORN_SERVER_CAPABILITIES"]
