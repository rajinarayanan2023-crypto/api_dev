"""Domain exceptions, decoupled from FastAPI/HTTP so the service layer never
imports Starlette. A single handler in app.main translates these to responses,
which keeps error bodies consistent and stops internals (stack traces, SQL
errors) from leaking to clients.
"""


class AppError(Exception):
    status_code = 400
    detail = "An unexpected error occurred."

    def __init__(self, detail: str | None = None):
        self.detail = detail or self.detail
        super().__init__(self.detail)


class NotFoundError(AppError):
    status_code = 404
    detail = "Resource not found."


class ConflictError(AppError):
    status_code = 409
    detail = "Resource already exists."


class UnauthorizedError(AppError):
    status_code = 401
    detail = "Invalid credentials."


class ForbiddenError(AppError):
    status_code = 403
    detail = "You do not have permission to perform this action."


class UnsupportedMediaTypeError(AppError):
    status_code = 415
    detail = "Unsupported file type."


class PayloadTooLargeError(AppError):
    status_code = 413
    detail = "File is too large."


class TooManyAttemptsError(AppError):
    """Account-level lockout (see LoginAttemptService) — distinct from
    slowapi's RateLimitExceeded, which is per-IP only and can't catch many
    different IPs guessing the same account's password. 429, same as a rate
    limit, since the right client behavior (back off, retry later) is
    identical either way.
    """

    status_code = 429
    detail = "Too many failed attempts. Please try again later."
