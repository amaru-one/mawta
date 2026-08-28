package httpapi

import (
	"net/http"

	"github.com/jackc/pgx/v5"

	"yanai-server/internal/domain"
	"yanai-server/internal/repo"
)

func (a *API) handleClassDashboard(w http.ResponseWriter, r *http.Request) {
	tc := tenantCtxFrom(r)
	classID, err := pathUUID(r, "classID")
	if err != nil {
		badRequest(w, "invalid classID")
		return
	}
	termIDParam := queryUUID(r, "term_id")

	var dashboard repo.ClassDashboard
	err = a.db.WithTenantTx(r.Context(), tc, func(tx pgx.Tx) error {
		today, err := resolveDate(r, tx, tc, r.URL.Query().Get("date"))
		if err != nil {
			return err
		}
		term, err := repo.ResolveTerm(r.Context(), tx, termIDParam)
		if err != nil {
			return err
		}
		dashboard, err = repo.GetClassDashboard(r.Context(), tx, classID, term, today)
		return err
	})
	if err != nil {
		writeError(w, err)
		return
	}
	writeJSON(w, http.StatusOK, dashboard)
}

func (a *API) handleClassSessions(w http.ResponseWriter, r *http.Request) {
	tc := tenantCtxFrom(r)
	classID, err := pathUUID(r, "classID")
	if err != nil {
		badRequest(w, "invalid classID")
		return
	}
	dir := r.URL.Query().Get("dir")
	if dir != "past" {
		dir = "upcoming"
	}
	limit := queryInt(r, "limit", 10)

	var sessions []repo.SessionSummary
	err = a.db.WithTenantTx(r.Context(), tc, func(tx pgx.Tx) error {
		today, err := resolveDate(r, tx, tc, r.URL.Query().Get("date"))
		if err != nil {
			return err
		}
		sessions, err = repo.ListSessions(r.Context(), tx, classID, today, dir, limit)
		return err
	})
	if err != nil {
		writeError(w, err)
		return
	}
	writeJSON(w, http.StatusOK, map[string]any{"sessions": sessions})
}

func (a *API) handleSessionStart(w http.ResponseWriter, r *http.Request) {
	tc := tenantCtxFrom(r)
	sessionID, err := pathUUID(r, "sessionID")
	if err != nil {
		badRequest(w, "invalid sessionID")
		return
	}
	err = a.db.WithTenantTx(r.Context(), tc, func(tx pgx.Tx) error {
		ct, err := tx.Exec(r.Context(), `
			update class_sessions
			   set status = $1, actual_start_at = now(), started_by_id = $2
			 where id = $3 and status = $4 and deleted_at is null
		`, domain.SessionInProgress, tc.TeacherID, sessionID, domain.SessionScheduled)
		if err != nil {
			return err
		}
		if ct.RowsAffected() == 0 {
			return conflictf("session cannot be started from its current state")
		}
		eid := sessionID
		return repo.LogEvent(r.Context(), tx, "session.started", "class_session", &eid, nil, nil, nil, &sessionID)
	})
	if err != nil {
		writeError(w, err)
		return
	}
	writeJSON(w, http.StatusOK, map[string]any{"status": domain.SessionInProgress})
}

func (a *API) handleSessionComplete(w http.ResponseWriter, r *http.Request) {
	tc := tenantCtxFrom(r)
	sessionID, err := pathUUID(r, "sessionID")
	if err != nil {
		badRequest(w, "invalid sessionID")
		return
	}
	err = a.db.WithTenantTx(r.Context(), tc, func(tx pgx.Tx) error {
		ct, err := tx.Exec(r.Context(), `
			update class_sessions
			   set status = $1, actual_end_at = now()
			 where id = $2 and status = $3 and deleted_at is null
		`, domain.SessionCompleted, sessionID, domain.SessionInProgress)
		if err != nil {
			return err
		}
		if ct.RowsAffected() == 0 {
			return conflictf("session cannot be completed from its current state")
		}
		eid := sessionID
		return repo.LogEvent(r.Context(), tx, "session.completed", "class_session", &eid, nil, nil, nil, &sessionID)
	})
	if err != nil {
		writeError(w, err)
		return
	}
	writeJSON(w, http.StatusOK, map[string]any{"status": domain.SessionCompleted})
}
