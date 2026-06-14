class AMPError(Exception):
    """Base exception for all AMP Client errors."""

    def __init__(self, message: str, status_code: int | None = None, details: dict | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.details = details or {}
