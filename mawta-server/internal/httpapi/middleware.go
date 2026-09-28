package httpapi

import (
	"context"
	"log/slog"
	"net/http"
	"time"

	"github.com/go-chi/chi/v5"
	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"

	authpkg "mawta-server/internal/auth"
	"mawta-server/internal/db"
	"mawta-server/internal/domain"
	"mawta-server/internal/repo"
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

// routePattern extracts the Chi route pattern from the request context.
// If the pattern is empty (e.g. 404 unmatched routes), it falls back to
// the request path.
func routePattern(r *http.Request) string {
	if pattern := chi.RouteContext(r.Context()).RoutePattern(); pattern != "" {
		return pattern
	}
	return r.URL.Path
}

func requestLogger(logger *slog.Logger) func(http.Handler) http.Handler {
	return func(next http.Handler) http.Handler {
		return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
			start := time.Now()
			sw := &statusWriter{ResponseWriter: w, status: http.StatusOK}
			next.ServeHTTP(sw, r)
			logger.Info("request",
				"request_id", requestIDFrom(r),
				"method", r.Method,
				"route", routePattern(r),
				"status", sw.status,
				"duration_ms", time.Since(start).Milliseconds(),
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

// sessionAuth replaces the old dev-header tenantAuth. It resolves the
// session cookie to a live user_sessions row (via db.WithAuthTx, the one
// pre-tenant lookup mode — see internal/db/SPEC.md), enforces absolute and
// idle expiry, gates on domain.LoginEnabledRoles so a role revoked or
// downgraded after login takes effect immediately, then resolves the
// teacher profile exactly as the old tenantAuth query did, inside a real
// tenant transaction.
func (a *API) sessionAuth(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		reqID := requestIDFrom(r)

		token := a.sessionTokenFrom(r)
		if token == "" {
			writeAppError(w, db.NewAppError(http.StatusUnauthorized, "missing_session", "no hay una sesión activa"))
			return
		}
		tokenHash := authpkg.HashSessionToken(token)

		var session repo.SessionRow
		err := a.db.WithAuthTx(r.Context(), reqID, func(tx pgx.Tx) error {
			var err error
			session, err = repo.FindLiveSession(r.Context(), tx, tokenHash)
			return err
		})
		if err == pgx.ErrNoRows {
			a.clearSessionCookie(w)
			writeAppError(w, db.NewAppError(http.StatusUnauthorized, "invalid_session", "sesión inválida"))
			return
		}
		if err != nil {
			writeError(w, err)
			return
		}

		now := time.Now()
		expired := session.ExpiresAt.Before(now)
		idle := now.Sub(session.LastSeenAt) > a.cfg.SessionIdleTimeout
		if expired || idle {
			reason := domain.SessionRevokeExpired
			if idle && !expired {
				reason = domain.SessionRevokeIdle
			}
			revokeErr := a.db.WithAuthTx(r.Context(), reqID, func(tx pgx.Tx) error {
				return repo.RevokeSession(r.Context(), tx, session.ID, reason)
			})
			if revokeErr != nil {
				a.logger.Error("revoke expired session", "error", revokeErr)
			}
			a.clearSessionCookie(w)
			writeAppError(w, db.NewAppError(http.StatusUnauthorized, "session_expired", "tu sesión expiró"))
			return
		}

		if !domain.LoginEnabledRoles[session.Role] {
			writeAppError(w, db.NewAppError(http.StatusForbidden, "role_not_enabled", "el acceso para tu rol aún no está disponible"))
			return
		}

		// Throttled — see repo.TouchSession — and done in the auth tx, not
		// the tenant tx below, so a handler rollback can't undo it.
		touchErr := a.db.WithAuthTx(r.Context(), reqID, func(tx pgx.Tx) error {
			return repo.TouchSession(r.Context(), tx, session.ID, time.Hour)
		})
		if touchErr != nil {
			a.logger.Warn("touch session", "error", touchErr)
		}

		tc := db.TenantCtx{TenantID: session.TenantID, ActorID: session.UserID, RequestID: reqID, Role: session.Role}
		var teacherID uuid.UUID
		err = a.db.WithTenantTx(r.Context(), tc, func(tx pgx.Tx) error {
			var err error
			teacherID, err = repo.ResolveTeacher(r.Context(), tx, session.UserID)
			return err
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
