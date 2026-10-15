package httpapi

import (
	"bytes"
	"context"
	"io"
	"log/slog"
	"net/http"
	"time"

	"github.com/go-chi/chi/v5"
	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"

	authpkg "mawta-server/internal/auth"
	"mawta-server/internal/db"
	"mawta-server/internal/domain"
	"mawta-server/internal/logging"
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

// requestLogger emits one completion event per request with the request_id,
// method, route pattern, status, duration, and — when body capture is
// enabled — the sanitized request/response bodies with their capture
// statuses.
//
// Body capture is off unless the logger was built with it on
// (logging.Setup reads REQUEST_BODY_CAPTURE, off by default). With it off,
// request/response stay null and request_capture/response_capture report
// "disabled"; the metadata is still emitted.
//
// Nothing here can fail a response: the capture is bounded
// (logging.MaxBodyBytes), the sanitization never sees a header or a query
// string, and the log write itself is the last thing that happens, after
// the response has already been written.
func requestLogger(logger *slog.Logger) func(http.Handler) http.Handler {
	return func(next http.Handler) http.Handler {
		return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
			start := time.Now()

			policy := logging.NewCapturePolicy(logging.RequestBodyCaptureFromEnv())

			// Request body: read a bounded copy, then hand the original
			// body to the handler. The handler sees the same bytes either
			// way; capture never truncates or rejects the exchange.
			var reqBody []byte
			if policy.Enabled && r.Body != nil {
				// MaxBytesReader+1 lets us detect "larger than the bound"
				// without reading the whole thing into memory.
				snapshot, err := io.ReadAll(io.LimitReader(r.Body, int64(policy.MaxBytes)+1))
				if err == nil {
					reqBody = snapshot
				}
				// A read error means no capture; the request proceeds with
				// whatever the handler can read. Never fail the exchange.
				r.Body = io.NopCloser(bytes.NewReader(reqBody))
			}

			captureLimit := 0
			if policy.Enabled {
				captureLimit = policy.MaxBytes
			}
			sw := newStatusWriter(w, captureLimit)

			// A panic that escapes the handler chain is recovered here, logged
			// with the request_id, and answered with an opaque 500 — the
			// client never sees the cause. When chi's Recoverer is mounted
			// inside this middleware (as the production router does), it
			// recovers first and writes the 500 through sw, so this is the
			// net for chains without it; either way the completion event
			// below carries the same request_id.
			func() {
				defer func() {
					if p := recover(); p != nil {
						cause := logging.SanitizeErrorCause(errorFromPanic(p))
						sw.recordErrorCause(cause)
						logger.Error("httpapi: recovered panic",
							"event", "http.panic",
							"request_id", requestIDFrom(r),
							"method", r.Method,
							"route", routePattern(r),
							"error", cause,
						)
						if !sw.wroteHeader {
							writeAppError(sw, db.NewAppError(http.StatusInternalServerError, "internal_error", "internal error"))
						}
					}
				}()
				next.ServeHTTP(sw, r)
			}()

			// The response body is captured by statusWriter.Write, bounded
			// to the same limit; anything past it is dropped, not truncated.
			reqCapture := policy.CaptureRequestBody(routePattern(r), r.Header.Get("Content-Type"), reqBody)
			respCapture := policy.CaptureResponseBody(routePattern(r), sw.Header().Get("Content-Type"), sw.body())

			attrs := []any{
				"event", "http.request",
				"request_id", requestIDFrom(r),
				"method", r.Method,
				"route", routePattern(r),
				"status", sw.status,
				"duration_ms", time.Since(start).Milliseconds(),
				"request", reqCapture.Value,
				"request_capture", string(reqCapture.Status),
				"response", respCapture.Value,
				"response_capture", string(respCapture.Status),
			}
			// A 5xx carries the sanitized cause under the same request_id as
			// this completion event, so the two lines join on request_id. The
			// client's envelope stays opaque.
			if sw.status >= 500 && sw.errorCause != "" {
				attrs = append(attrs, "error", sw.errorCause)
			}
			logger.Info("request", attrs...)
		})
	}
}

// statusWriter records the status and a bounded copy of the response body.
// The copy exists only for the completion event; the real bytes go to the
// client as they are written, so streaming and Content-Length are untouched.
type statusWriter struct {
	http.ResponseWriter
	status int
	// wroteHeader records that a status line has already been sent, so the
	// panic recovery does not try to write a second one.
	wroteHeader bool
	// errorCause is the sanitized cause of a 5xx, recorded by writeError so
	// the completion event can log it under the request_id.
	errorCause string
	// capture is the bounded response snapshot for logging. It is written
	// only while it is under the capture limit; past the limit the snapshot
	// stops growing and the completion event reports too_large.
	capture []byte
	// captureLimit is 0 when capture is off, so the snapshot never allocates.
	captureLimit int
}

func (w *statusWriter) WriteHeader(status int) {
	w.status = status
	w.wroteHeader = true
	w.ResponseWriter.WriteHeader(status)
}

// recordErrorCause implements errorCauseRecorder (respond.go).
func (w *statusWriter) recordErrorCause(cause string) {
	w.errorCause = cause
}

func (w *statusWriter) Write(p []byte) (int, error) {
	if !w.wroteHeader {
		w.WriteHeader(http.StatusOK)
	}
	if w.captureLimit > 0 && len(w.capture) <= w.captureLimit {
		room := w.captureLimit + 1 - len(w.capture)
		if room > len(p) {
			room = len(p)
		}
		w.capture = append(w.capture, p[:room]...)
	}
	return w.ResponseWriter.Write(p)
}

// body returns the captured snapshot, or nil when capture is off. The +1
// headroom in Write lets CaptureResponseBody see "exceeds the bound" rather
// than "exactly at the bound".
func (w *statusWriter) body() []byte {
	if w.captureLimit == 0 {
		return nil
	}
	return w.capture
}

// newStatusWriter builds the response recorder for one request. captureLimit
// is logging.MaxBodyBytes when capture is on, 0 when off.
func newStatusWriter(w http.ResponseWriter, captureLimit int) *statusWriter {
	return &statusWriter{ResponseWriter: w, status: http.StatusOK, captureLimit: captureLimit}
}

// errorFromPanic turns a recovered panic value into an error so its message
// can be sanitized the same way an error's is.
func errorFromPanic(p any) error {
	if err, ok := p.(error); ok {
		return err
	}
	return &panicError{value: p}
}

type panicError struct {
	value any
}

func (e *panicError) Error() string {
	if s, ok := e.value.(string); ok {
		return "panic: " + s
	}
	return "panic: non-error value"
}

// sessionAuth replaces the old dev-header tenantAuth. It resolves the
// session cookie to a live user_sessions row (via db.WithAuthTx, the one
// pre-tenant lookup mode — see internal/db/SPEC.md), enforces absolute and
// idle expiry, gates on domain.LoginEnabledRoles so a role revoked or
// downgraded after login takes effect immediately, then resolves the
// teacher profile exactly as the old tenantAuth query did, inside a real
// tenant transaction.
func (a *API) sessionAuth(next http.Handler) http.Handler {
	return a.authenticate(a.requireTeacher(next))
}

// authenticate is the role-independent half of sessionAuth: it validates the
// session and stores the tenant context without a teacher. Routes open to
// every logged-in role (GET /me) mount it directly.
func (a *API) authenticate(next http.Handler) http.Handler {
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
		ctx := context.WithValue(r.Context(), tenantCtxKey, tc)
		next.ServeHTTP(w, r.WithContext(ctx))
	})
}

// requireTeacher is the teacher half of sessionAuth: it resolves the teacher
// profile of an authenticated session. Any other role gets 403.
func (a *API) requireTeacher(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		tc := tenantCtxFrom(r)
		if tc.Role != domain.RoleTeacher {
			writeAppError(w, db.NewAppError(http.StatusForbidden, "not_a_member", "actor has no active teaching membership in this tenant"))
			return
		}
		var teacherID uuid.UUID
		err := a.db.WithTenantTx(r.Context(), tc, func(tx pgx.Tx) error {
			var err error
			teacherID, err = repo.ResolveTeacher(r.Context(), tx, tc.ActorID)
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
