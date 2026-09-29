package httpapi

import (
	"encoding/json"
	"log/slog"
	"net/http"

	"mawta-server/internal/db"
	"mawta-server/internal/logging"
)

// errorCauseRecorder is implemented by the request logger's response writer.
// When an error path renders a 5xx, it stashes the sanitized cause there so
// the completion event can log it under the same request_id — the one place
// that knows the request_id, because handlers call writeError with only the
// writer. A plain http.ResponseWriter (a handler called directly in a test)
// simply does not implement it, and the cause is logged here instead.
type errorCauseRecorder interface {
	recordErrorCause(cause string)
}

// logInternalError emits the sanitized cause of a 5xx. It uses
// slog.Default(), which cmd/api sets to the configured JSON logger, so every
// application log entry — including this one — goes through it.
func logInternalError(err error, reqID string) {
	attrs := []any{"error", logging.SanitizeErrorCause(err)}
	if reqID != "" {
		attrs = append(attrs, "request_id", reqID)
	}
	slog.Error("httpapi: internal error", attrs...)
}

func writeJSON(w http.ResponseWriter, status int, v any) {
	w.Header().Set("Content-Type", "application/json; charset=utf-8")
	w.WriteHeader(status)
	if v == nil {
		return
	}
	if err := json.NewEncoder(w).Encode(v); err != nil {
		slog.Error("httpapi: encode response", "error", err)
	}
}

type errorEnvelope struct {
	Error errorBody `json:"error"`
}

type errorBody struct {
	Code    string `json:"code"`
	Message string `json:"message"`
	Hint    string `json:"hint,omitempty"`
}

// writeError maps err to an AppError and renders the envelope. 5xx envelopes
// are deliberately opaque to the client; the sanitized cause goes to the log
// (here, and — when the request logger's writer is in play — into the
// completion event under the request_id).
func writeError(w http.ResponseWriter, err error) {
	appErr := db.MapError(err)
	if appErr.Status >= 500 {
		logInternalError(err, "")
		if rec, ok := w.(errorCauseRecorder); ok {
			rec.recordErrorCause(logging.SanitizeErrorCause(err))
		}
	}
	writeJSON(w, appErr.Status, errorEnvelope{Error: errorBody{
		Code:    appErr.Code,
		Message: appErr.Message,
		Hint:    appErr.Hint,
	}})
}

func writeAppError(w http.ResponseWriter, appErr *db.AppError) {
	writeJSON(w, appErr.Status, errorEnvelope{Error: errorBody{
		Code:    appErr.Code,
		Message: appErr.Message,
		Hint:    appErr.Hint,
	}})
}

// writeErrorWithRequestID logs a 5xx error with the request_id for correlation.
// The error cause is logged server-side but NOT exposed to clients.
func writeErrorWithRequestID(w http.ResponseWriter, err error, reqID string) {
	appErr := db.MapError(err)
	if appErr.Status >= 500 {
		logInternalError(err, reqID)
		if rec, ok := w.(errorCauseRecorder); ok {
			rec.recordErrorCause(logging.SanitizeErrorCause(err))
		}
	}
	writeJSON(w, appErr.Status, errorEnvelope{Error: errorBody{
		Code:    appErr.Code,
		Message: appErr.Message,
		Hint:    appErr.Hint,
	}})
}
