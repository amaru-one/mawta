package httpapi

import (
	"net/http"

	"github.com/jackc/pgx/v5"

	"mawta-server/internal/repo"
)

func (a *API) handleMe(w http.ResponseWriter, r *http.Request) {
	tc := tenantCtxFrom(r)
	var resp repo.MeResponse
	err := a.db.WithTenantTx(r.Context(), tc, func(tx pgx.Tx) error {
		var err error
		resp, err = repo.GetMe(r.Context(), tx, tc.TeacherID)
		return err
	})
	if err != nil {
		writeError(w, err)
		return
	}
	resp.Role = tc.Role
	writeJSON(w, http.StatusOK, resp)
}
