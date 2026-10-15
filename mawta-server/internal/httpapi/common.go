package httpapi

import (
	"net/http"

	"github.com/jackc/pgx/v5"

	"mawta-server/internal/db"
	"mawta-server/internal/domain"
	"mawta-server/internal/repo"
)

// handleMe answers for every logged-in role. A director has no teacher
// profile, so it gets its own lookup; a teacher's profile is resolved here
// because GET /me is mounted behind authenticate, not sessionAuth.
func (a *API) handleMe(w http.ResponseWriter, r *http.Request) {
	tc := tenantCtxFrom(r)
	var resp repo.MeResponse
	err := a.db.WithTenantTx(r.Context(), tc, func(tx pgx.Tx) error {
		if tc.Role == domain.RoleDirector {
			var err error
			resp, err = repo.GetDirectorMe(r.Context(), tx, tc.ActorID)
			return err
		}
		teacherID, err := repo.ResolveTeacher(r.Context(), tx, tc.ActorID)
		if err != nil {
			return err
		}
		resp, err = repo.GetMe(r.Context(), tx, teacherID)
		return err
	})
	if err == pgx.ErrNoRows {
		writeAppError(w, db.NewAppError(http.StatusForbidden, "not_a_member", "actor has no active teaching membership in this tenant"))
		return
	}
	if err != nil {
		writeError(w, err)
		return
	}
	resp.Role = tc.Role
	writeJSON(w, http.StatusOK, resp)
}
