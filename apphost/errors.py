"""Application errors that carry an HTTP status.

Anything a user can act on must be an ``AppError`` so the panel shows a real
message instead of an opaque 500.
"""

from __future__ import annotations


class AppError(RuntimeError):
    status = 400
    code = "error"

    def __init__(self, message: str, *, code: str | None = None) -> None:
        super().__init__(message)
        if code:
            self.code = code
        self.message = message


class ValidationError(AppError):
    status = 400
    code = "validation_error"


class NotFoundError(AppError):
    status = 404
    code = "not_found"


class ConflictError(AppError):
    status = 409
    code = "conflict"


class AuthError(AppError):
    status = 401
    code = "unauthorized"


class ForbiddenError(AppError):
    status = 403
    code = "forbidden"


class ToolchainError(AppError):
    status = 503
    code = "toolchain_missing"
