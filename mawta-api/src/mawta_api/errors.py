"""Typed API errors and the Postgres error mapping."""

from dataclasses import dataclass

import psycopg


class AppError(Exception):
    """An error carrying an HTTP status and a stable code."""

    def __init__(self, status: int, code: str, message: str, hint: str = "") -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message
        self.hint = hint

    def envelope(self) -> dict:
        body: dict = {"code": self.code, "message": self.message}
        if self.hint:
            body["hint"] = self.hint
        return {"error": body}


class NotFound(Exception):
    """A lookup matched nothing. Maps to 404 not_found."""


def bad_request(message: str) -> AppError:
    return AppError(400, "bad_request", message)


def unprocessable(message: str) -> AppError:
    """Input that is well formed but violates a stated constraint."""
    return AppError(422, "unprocessable_entity", message)


def conflict(message: str) -> AppError:
    """A state-transition guard not backed by a database constraint."""
    return AppError(409, "conflict", message)


# Constraints whose violation is a domain error with a stable code. The repo
# checks first; the constraint still catches two requests racing past the check.
_CONSTRAINT_ERRORS = {
    "learning_experiences_no_overlap": AppError(
        409, "experience_overlap", "las fechas se cruzan con otra experiencia de esta clase"
    ),
    "session_outline_entries_date_key": AppError(
        409, "session_date_taken", "ya hay una sesión planificada en esa fecha"
    ),
}

_SQLSTATE = {
    "23001": (409, "restrict_violation"),
    "23503": (422, "foreign_key_violation"),
    "23505": (409, "unique_violation"),
    "23514": (422, "check_violation"),
    "23P01": (409, "exclusion_violation"),
}


def map_error(exc: BaseException) -> AppError:
    """Classify any error into an AppError. Postgres hints are preserved so the
    operational hints baked into the schema's triggers reach the caller."""
    if isinstance(exc, AppError):
        return exc
    if isinstance(exc, NotFound):
        return AppError(404, "not_found", "resource not found")
    if isinstance(exc, psycopg.Error) and exc.diag.sqlstate:
        known = _CONSTRAINT_ERRORS.get(exc.diag.constraint_name or "")
        if known is not None:
            return AppError(known.status, known.code, known.message)
        status, code = _SQLSTATE.get(exc.diag.sqlstate, (500, "database_error"))
        return AppError(
            status, code, exc.diag.message_primary or str(exc), exc.diag.message_hint or ""
        )
    return AppError(500, "internal_error", "internal error")


@dataclass(frozen=True)
class Forbidden:
    code: str
    message: str
