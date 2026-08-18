package db

import (
	"errors"
	"net/http"

	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgconn"
)

// AppError is a typed error carrying an HTTP status and a stable code, so
// httpapi can render it without knowing about Postgres.
type AppError struct {
	Status  int
	Code    string
	Message string
	Hint    string
}

func (e *AppError) Error() string { return e.Message }

func NewAppError(status int, code, message string) *AppError {
	return &AppError{Status: status, Code: code, Message: message}
}

// MapError classifies a repo-layer error into an AppError. Postgres SQLSTATEs
// are mapped by class; PgError.Hint is preserved so the operational hints
// baked into the schema's triggers (e.g. "insert a superseding row instead
// of updating") reach the API caller.
func MapError(err error) *AppError {
	if err == nil {
		return nil
	}

	var appErr *AppError
	if errors.As(err, &appErr) {
		return appErr
	}

	if errors.Is(err, pgx.ErrNoRows) {
		return &AppError{Status: http.StatusNotFound, Code: "not_found", Message: "resource not found"}
	}

	var pgErr *pgconn.PgError
	if errors.As(err, &pgErr) {
		mapped := &AppError{Message: pgErr.Message, Hint: pgErr.Hint}
		switch pgErr.Code {
		case "23001": // restrict_violation
			mapped.Status = http.StatusConflict
			mapped.Code = "restrict_violation"
		case "23503": // foreign_key_violation
			mapped.Status = http.StatusUnprocessableEntity
			mapped.Code = "foreign_key_violation"
		case "23505": // unique_violation
			mapped.Status = http.StatusConflict
			mapped.Code = "unique_violation"
		case "23514": // check_violation
			mapped.Status = http.StatusUnprocessableEntity
			mapped.Code = "check_violation"
		case "23P01": // exclusion_violation
			mapped.Status = http.StatusConflict
			mapped.Code = "exclusion_violation"
		default:
			mapped.Status = http.StatusInternalServerError
			mapped.Code = "database_error"
		}
		return mapped
	}

	return &AppError{Status: http.StatusInternalServerError, Code: "internal_error", Message: "internal error"}
}
