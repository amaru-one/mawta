package httpapi

import (
	"net/http"
	"time"

	"github.com/jackc/pgx/v5"

	"mawta-server/internal/repo"
)

func (a *API) handleListNotifications(w http.ResponseWriter, r *http.Request) {
	tc := tenantCtxFrom(r)
	kind := r.URL.Query().Get("kind")
	limit := queryInt(r, "limit", 50)

	var before *time.Time
	if v := r.URL.Query().Get("before"); v != "" {
		t, err := time.Parse(time.RFC3339, v)
		if err != nil {
			badRequest(w, "invalid before timestamp")
			return
		}
		before = &t
	}

	var notifications []repo.NotificationEntry
	err := a.db.WithTenantTx(r.Context(), tc, func(tx pgx.Tx) error {
		var err error
		notifications, err = repo.ListNotifications(r.Context(), tx, tc.TeacherID, kind, limit, before)
		return err
	})
	if err != nil {
		writeError(w, err)
		return
	}
	writeJSON(w, http.StatusOK, map[string]any{"notifications": notifications})
}

func (a *API) handleMarkNotificationRead(w http.ResponseWriter, r *http.Request) {
	tc := tenantCtxFrom(r)
	notificationID, err := pathUUID(r, "notificationID")
	if err != nil {
		badRequest(w, "invalid notificationID")
		return
	}
	err = a.db.WithTenantTx(r.Context(), tc, func(tx pgx.Tx) error {
		return repo.MarkNotificationRead(r.Context(), tx, notificationID, tc.TeacherID)
	})
	if err != nil {
		writeError(w, err)
		return
	}
	writeJSON(w, http.StatusOK, map[string]any{"ok": true})
}

func (a *API) handleMarkAllNotificationsRead(w http.ResponseWriter, r *http.Request) {
	tc := tenantCtxFrom(r)
	var n int
	err := a.db.WithTenantTx(r.Context(), tc, func(tx pgx.Tx) error {
		var err error
		n, err = repo.MarkAllNotificationsRead(r.Context(), tx, tc.TeacherID)
		return err
	})
	if err != nil {
		writeError(w, err)
		return
	}
	writeJSON(w, http.StatusOK, map[string]any{"marked_read": n})
}
