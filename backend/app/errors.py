class ApiError(Exception):
    """Represents an error that must be serialized using the documented error contract."""

    def __init__(self, status_code: int, code: str, message: str, retryable: bool, details=None):
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.retryable = retryable
        self.details = details or []
