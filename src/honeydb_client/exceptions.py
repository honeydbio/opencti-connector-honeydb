class HoneyDBError(Exception):
    """Base class for every error raised by `HoneyDBClient`."""


class HoneyDBAuthError(HoneyDBError):
    """HTTP 401: the API ID / API key pair was rejected."""


class HoneyDBPlanError(HoneyDBError):
    """HTTP 402: the account's plan does not allow the request."""


class HoneyDBQuotaError(HoneyDBError):
    """HTTP 429: the API quota for the current window is exhausted."""

    def __init__(self, message: str, quota_headers: dict[str, str] | None = None):
        super().__init__(message)
        self.quota_headers: dict[str, str] = quota_headers or {}


class HoneyDBTransientError(HoneyDBError):
    """Network failure or 5xx that persisted after the bounded retry."""


class HoneyDBResponseError(HoneyDBError):
    """2xx response whose body is not the expected JSON array."""
