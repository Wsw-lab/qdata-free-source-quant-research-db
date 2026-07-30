class QDataError(Exception):
    """Base exception for qdata SDK errors."""


class QDataValidationError(QDataError):
    """Raised when request parameters are invalid."""


class QDataNotFoundError(QDataError):
    """Raised when requested data is not available."""


class QDataProviderError(QDataError):
    """Raised when an upstream data provider cannot return usable data."""
