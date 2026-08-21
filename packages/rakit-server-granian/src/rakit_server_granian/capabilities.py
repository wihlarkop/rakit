from rakit_server import ServerCapabilities

GRANIAN_SERVER_CAPABILITIES = ServerCapabilities(
    reload=True,
    workers=True,
    app_object=False,
    import_string=True,
)

__all__ = ["GRANIAN_SERVER_CAPABILITIES"]
