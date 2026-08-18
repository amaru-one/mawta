package httpapi

import (
	"net/http"
	"strconv"

	"github.com/go-chi/chi/v5"
	"github.com/google/uuid"

	"yanai-server/internal/db"
)

func pathUUID(r *http.Request, name string) (uuid.UUID, error) {
	return uuid.Parse(chi.URLParam(r, name))
}

func queryUUID(r *http.Request, name string) uuid.UUID {
	v := r.URL.Query().Get(name)
	if v == "" {
		return uuid.Nil
	}
	id, err := uuid.Parse(v)
	if err != nil {
		return uuid.Nil
	}
	return id
}

func queryInt(r *http.Request, name string, def int) int {
	v := r.URL.Query().Get(name)
	if v == "" {
		return def
	}
	n, err := strconv.Atoi(v)
	if err != nil {
		return def
	}
	return n
}

func badRequest(w http.ResponseWriter, message string) {
	writeAppError(w, db.NewAppError(http.StatusBadRequest, "bad_request", message))
}

// conflictf builds a 409 AppError for state-transition guards that aren't
// backed by a database constraint (e.g. "0 rows updated").
func conflictf(message string) *db.AppError {
	return db.NewAppError(http.StatusConflict, "conflict", message)
}
