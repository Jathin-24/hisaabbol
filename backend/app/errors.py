class ApiError(Exception):
    """Raised anywhere; rendered as {"error": {"code", "message", ...}} with the given HTTP status."""

    def __init__(self, status: int, code: str, message: str, **extra):
        self.status, self.code, self.message, self.extra = status, code, message, extra
        super().__init__(message)
