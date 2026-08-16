class ServerError(RuntimeError):
    pass


class ServerConfigurationError(ServerError, ValueError):
    pass


class InvalidServerTargetError(ServerConfigurationError):
    pass


class ServerAdapterNotFoundError(ServerError):
    pass


class ServerAdapterConflictError(ServerError):
    pass
