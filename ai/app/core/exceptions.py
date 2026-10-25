class AIServiceError(Exception):
    """Base error carrying a stable public error code."""

    code = "AI_SERVICE_ERROR"
    retryable = False


class DependencyUnavailable(AIServiceError):
    code = "DEPENDENCY_UNAVAILABLE"
    retryable = True


class BackendAccessDenied(AIServiceError):
    code = "BACKEND_ACCESS_DENIED"


class BackendNotFound(AIServiceError):
    code = "BACKEND_NOT_FOUND"


class BackendConflict(AIServiceError):
    code = "BACKEND_CONFLICT"


class ToolValidationError(AIServiceError):
    code = "TOOL_VALIDATION_ERROR"


class ToolNotAllowed(AIServiceError):
    code = "TOOL_NOT_ALLOWED"


class ModelProtocolError(AIServiceError):
    code = "MODEL_PROTOCOL_ERROR"
