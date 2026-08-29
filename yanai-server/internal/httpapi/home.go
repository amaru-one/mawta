package httpapi

import (
	"net/http"
	"time"

	"github.com/jackc/pgx/v5"

	"yanai-server/internal/db"
	"yanai-server/internal/repo"
)

func (a *API) handleHome(w http.ResponseWriter, r *http.Request) {
	tc := tenantCtxFrom(r)
	dateParam := r.URL.Query().Get("date")

	var resp repo.HomeResponse
	err := a.db.WithTenantTx(r.Context(), tc, func(tx pgx.Tx) error {
		d, err := resolveDate(r, tx, tc, dateParam)
		if err != nil {
			return err
		}
		resp, err = repo.GetHome(r.Context(), tx, tc.TeacherID, d)
		return err
	})
	if err != nil {
		writeError(w, err)
		return
	}
	writeJSON(w, http.StatusOK, resp)
}

// resolveDate parses ?date=YYYY-MM-DD, defaulting to "today" in the
// tenant's timezone when absent.
func resolveDate(r *http.Request, tx pgx.Tx, tc db.TenantCtx, dateParam string) (time.Time, error) {
	if dateParam != "" {
		return time.Parse("2006-01-02", dateParam)
	}
	return repo.TenantToday(r.Context(), tx, tc.TenantID)
}
