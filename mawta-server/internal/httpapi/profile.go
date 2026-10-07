package httpapi

import (
	"net/http"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"

	"mawta-server/internal/repo"
)

func (a *API) handleProfile(w http.ResponseWriter, r *http.Request) {
	tc := tenantCtxFrom(r)
	termIDParam := queryUUID(r, "term_id")

	var resp repo.ProfileResponse
	err := a.db.WithTenantTx(r.Context(), tc, func(tx pgx.Tx) error {
		today, err := resolveDate(r, tx, tc, r.URL.Query().Get("date"))
		if err != nil {
			return err
		}
		term, err := repo.ResolveTerm(r.Context(), tx, uuid.Nil, termIDParam)
		if err != nil {
			return err
		}
		resp, err = repo.GetProfile(r.Context(), tx, tc.TeacherID, term, today)
		return err
	})
	if err != nil {
		writeError(w, err)
		return
	}
	writeJSON(w, http.StatusOK, resp)
}
