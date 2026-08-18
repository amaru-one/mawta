package httpapi

import (
	"context"
	"log/slog"
	"net/http"
	"time"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"

	"yanai-server/internal/db"
)

type ctxKey int

const tenantCtxKey ctxKey = iota

func tenantCtxFrom(r *http.Request) db.TenantCtx {
	tc, _ := r.Context().Value(tenantCtxKey).(db.TenantCtx)
	return tc
}

// requestID assigns or propagates X-Request-ID and stashes it for logging
// and for app.request_id correlation.
func requestID(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		id := r.Header.Get("X-Request-ID")
		if id == "" {
			id = uuid.NewString()
		}
		w.Header().Set("X-Request-ID", id)
		ctx := context.WithValue(r.Context(), requestIDKey, id)
		next.ServeHTTP(w, r.WithContext(ctx))
	})
}

type requestIDKeyType int

const requestIDKey requestIDKeyType = 0

func requestIDFrom(r *http.Request) string {
	id, _ := r.Context().Value(requestIDKey).(string)
	return id
}

func requestLogger(logger *slog.Logger) func(http.Handler) http.Handler {
	return func(next http.Handler) http.Handler {
		return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
			start := time.Now()
			sw := &statusWriter{ResponseWriter: w, status: http.StatusOK}
			next.ServeHTTP(sw, r)
			logger.Info("request",
				"method", r.Method,
				"path", r.URL.Path,
				"status", sw.status,
				"duration_ms", time.Since(start).Milliseconds(),
				"request_id", requestIDFrom(r),
			)
		})
	}
}

type statusWriter struct {
	http.ResponseWriter
	status int
}

func (w *statusWriter) WriteHeader(status int) {
	w.status = status
	w.ResponseWriter.WriteHeader(status)
}

// tenantAuth implements the dev-header auth model: X-Tenant-ID and
// X-Actor-ID must be valid UUIDs, and the actor must have an active
// membership (and a teacher profile) in that tenant. users RLS is only
// visible through memberships, so validation goes through memberships
// directly rather than selecting from users.
func (a *API) tenantAuth(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		tenantID, err := uuid.Parse(r.Header.Get("X-Tenant-ID"))
		if err != nil {
			writeAppError(w, db.NewAppError(http.StatusUnauthorized, "missing_tenant", "X-Tenant-ID header is required and must be a UUID"))
			return
		}
		actorID, err := uuid.Parse(r.Header.Get("X-Actor-ID"))
		if err != nil {
			writeAppError(w, db.NewAppError(http.StatusUnauthorized, "missing_actor", "X-Actor-ID header is required and must be a UUID"))
			return
		}

		reqID := requestIDFrom(r)
		tc := db.TenantCtx{TenantID: tenantID, ActorID: actorID, RequestID: reqID}

		var teacherID uuid.UUID
		err = a.db.WithTenantTx(r.Context(), tc, func(tx pgx.Tx) error {
			return tx.QueryRow(r.Context(), `
				select t.id
				  from memberships m
				  join teachers t on t.membership_id = m.id and t.deleted_at is null
				 where m.user_id = $1
				   and m.tenant_id = app.current_tenant_id()
				   and m.status = 'active'
				   and m.deleted_at is null
			`, actorID).Scan(&teacherID)
		})
		if err != nil {
			if err == pgx.ErrNoRows {
				writeAppError(w, db.NewAppError(http.StatusForbidden, "not_a_member", "actor has no active teaching membership in this tenant"))
				return
			}
			writeError(w, err)
			return
		}

		tc.TeacherID = teacherID
		ctx := context.WithValue(r.Context(), tenantCtxKey, tc)
		next.ServeHTTP(w, r.WithContext(ctx))
	})
}
