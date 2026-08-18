package httpapi

import (
	"encoding/json"
	"log/slog"
	"net/http"

	"yanai-server/internal/db"
)

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

func writeError(w http.ResponseWriter, err error) {
	appErr := db.MapError(err)
	if appErr.Status >= 500 {
		// 5xx envelopes are deliberately opaque; keep the cause in the log.
		slog.Error("httpapi: internal error", "error", err)
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
