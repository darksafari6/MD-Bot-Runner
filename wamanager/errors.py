"""Errors that carry an HTTP status so the API can answer correctly."""

from __future__ import annotations


class AppError(Exception):
    status = 500

    def __init__(self, message: str, status: int | None = None) -> None:
        super().__init__(message)
        self.message = message
        if status is not None:
            self.status = status


class ValidationError(AppError):
    status = 400


class NotFoundError(AppError):
    status = 404


class ConflictError(AppError):
    """Valid request, but the resource is in the wrong state (e.g. bot stopped)."""

    status = 409


class UpstreamError(AppError):
    """A dependency failed — WhatsApp, an AI provider, ..."""

    status = 502
