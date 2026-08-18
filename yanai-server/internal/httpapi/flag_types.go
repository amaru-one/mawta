package httpapi

import (
	"net/http"

	"github.com/jackc/pgx/v5"

	"yanai-server/internal/repo"
)

func (a *API) handleListFlagTypes(w http.ResponseWriter, r *http.Request) {
	tc := tenantCtxFrom(r)
	var flagTypes []repo.FlagType
	err := a.db.WithTenantTx(r.Context(), tc, func(tx pgx.Tx) error {
		var err error
		flagTypes, err = repo.ListFlagTypes(r.Context(), tx)
		return err
	})
	if err != nil {
		writeError(w, err)
		return
	}
	writeJSON(w, http.StatusOK, map[string]any{"flag_types": flagTypes})
}
