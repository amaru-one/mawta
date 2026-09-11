package httpapi

import (
	"encoding/json"
	"net"
	"net/http"
	"net/netip"
	"strings"
	"time"

	"github.com/jackc/pgx/v5"

	authpkg "yanai-server/internal/auth"
	"yanai-server/internal/db"
	"yanai-server/internal/domain"
	"yanai-server/internal/repo"
)

type loginRequest struct {
	Username string `json:"username"`
	Password string `json:"password"`
}

// handleLogin resolves a username+password to a session, sets the session
// cookie, and returns the same payload GET /me does. Mounted outside
// sessionAuth — there is no session yet at this point, by definition.
func (a *API) handleLogin(w http.ResponseWriter, r *http.Request) {
	var req loginRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		badRequest(w, "invalid body")
		return
	}
	username := strings.ToLower(strings.TrimSpace(req.Username))
	if username == "" || req.Password == "" {
		writeAppError(w, db.NewAppError(http.StatusUnauthorized, "invalid_credentials", "usuario o contraseña incorrectos"))
		return
	}

	reqID := requestIDFrom(r)

	var candidate repo.LoginCandidate
	var found bool
	err := a.db.WithAuthTx(r.Context(), reqID, func(tx pgx.Tx) error {
		var err error
		candidate, err = repo.FindLoginCandidate(r.Context(), tx, username)
		if err == pgx.ErrNoRows {
			found = false
			return nil
		}
		if err != nil {
			return err
		}
		found = true
		return nil
	})
	if err != nil {
		writeError(w, err)
		return
	}

	if !found {
		// Always verify against a real bcrypt hash so a missing username
		// takes the same time as a wrong password on a real one.
		_ = authpkg.VerifyPassword(authpkg.DummyHash(), req.Password)
		a.logger.Info("login failed", "reason", "no_such_user", "username", username, "request_id", reqID)
		writeAppError(w, db.NewAppError(http.StatusUnauthorized, "invalid_credentials", "usuario o contraseña incorrectos"))
		return
	}

	if candidate.LockedUntil != nil && candidate.LockedUntil.After(time.Now()) {
		writeAppError(w, db.NewAppError(http.StatusTooManyRequests, "account_locked", "demasiados intentos; espera unos minutos"))
		return
	}

	if candidate.Status != "active" {
		// Not a distinct code — an invited/suspended/deactivated account
		// must be indistinguishable from a wrong password.
		a.logger.Info("login failed", "reason", "inactive_status", "user_id", candidate.UserID, "status", candidate.Status, "request_id", reqID)
		writeAppError(w, db.NewAppError(http.StatusUnauthorized, "invalid_credentials", "usuario o contraseña incorrectos"))
		return
	}

	if verifyErr := authpkg.VerifyPassword(candidate.PasswordHash, req.Password); verifyErr != nil {
		failErr := a.db.WithAuthTx(r.Context(), reqID, func(tx pgx.Tx) error {
			return repo.RecordLoginFailure(r.Context(), tx, candidate.UserID, a.cfg.LoginMaxFailures, a.cfg.LoginLockout)
		})
		if failErr != nil {
			a.logger.Error("record login failure", "error", failErr)
		}
		a.logger.Info("login failed", "reason", "bad_password", "user_id", candidate.UserID, "request_id", reqID)
		writeAppError(w, db.NewAppError(http.StatusUnauthorized, "invalid_credentials", "usuario o contraseña incorrectos"))
		return
	}

	var membership repo.ResolvedMembership
	err = a.db.WithAuthTx(r.Context(), reqID, func(tx pgx.Tx) error {
		var err error
		membership, err = repo.ResolveMembership(r.Context(), tx, candidate.UserID)
		return err
	})
	if err == pgx.ErrNoRows {
		writeAppError(w, db.NewAppError(http.StatusForbidden, "no_membership", "tu cuenta no está activa en ningún colegio"))
		return
	}
	if err != nil {
		writeError(w, err)
		return
	}

	if !domain.LoginEnabledRoles[membership.Role] {
		// Checked after the password, deliberately: this must not be usable
		// as a username/role enumeration oracle.
		writeAppError(w, db.NewAppError(http.StatusForbidden, "role_not_enabled", "el acceso para tu rol aún no está disponible"))
		return
	}

	tc := db.TenantCtx{TenantID: membership.TenantID, ActorID: candidate.UserID, RequestID: reqID, Role: membership.Role}
	var meResp repo.MeResponse
	err = a.db.WithTenantTx(r.Context(), tc, func(tx pgx.Tx) error {
		teacherID, err := repo.ResolveTeacher(r.Context(), tx, candidate.UserID)
		if err != nil {
			return err
		}
		meResp, err = repo.GetMe(r.Context(), tx, teacherID)
		if err != nil {
			return err
		}
		return repo.LogEvent(r.Context(), tx, "auth.login", "user", &tc.ActorID, nil, nil, nil, nil)
	})
	if err == pgx.ErrNoRows {
		writeAppError(w, db.NewAppError(http.StatusForbidden, "not_a_teacher_profile", "tu cuenta no tiene un perfil docente en este colegio"))
		return
	}
	if err != nil {
		writeError(w, err)
		return
	}

	token, tokenHash, err := authpkg.NewSessionToken()
	if err != nil {
		writeError(w, err)
		return
	}
	expiresAt := time.Now().Add(a.cfg.SessionTTL)

	err = a.db.WithAuthTx(r.Context(), reqID, func(tx pgx.Tx) error {
		_, err := repo.CreateSession(r.Context(), tx, repo.NewSession{
			TokenHash:    tokenHash,
			UserID:       candidate.UserID,
			TenantID:     membership.TenantID,
			MembershipID: membership.MembershipID,
			Role:         membership.Role,
			ExpiresAt:    expiresAt,
			UserAgent:    r.UserAgent(),
			IP:           clientIP(r),
		})
		if err != nil {
			return err
		}
		if err := repo.RecordLoginSuccess(r.Context(), tx, candidate.UserID); err != nil {
			return err
		}
		if _, err := repo.PruneSessions(r.Context(), tx, 30*24*time.Hour); err != nil {
			a.logger.Warn("prune sessions", "error", err)
		}
		return nil
	})
	if err != nil {
		writeError(w, err)
		return
	}

	a.setSessionCookie(w, token, expiresAt)
	meResp.Role = membership.Role
	writeJSON(w, http.StatusOK, meResp)
}

// handleLogout revokes the session if a cookie is present and always clears
// the cookie. Idempotent.
func (a *API) handleLogout(w http.ResponseWriter, r *http.Request) {
	token := a.sessionTokenFrom(r)
	if token != "" {
		err := a.db.WithAuthTx(r.Context(), requestIDFrom(r), func(tx pgx.Tx) error {
			return repo.RevokeSessionByTokenHash(r.Context(), tx, authpkg.HashSessionToken(token), domain.SessionRevokeLogout)
		})
		if err != nil {
			a.logger.Error("revoke session", "error", err)
		}
	}
	a.clearSessionCookie(w)
	w.WriteHeader(http.StatusNoContent)
}

func (a *API) setSessionCookie(w http.ResponseWriter, token string, expires time.Time) {
	http.SetCookie(w, &http.Cookie{
		Name:     a.cfg.SessionCookieName,
		Value:    token,
		Path:     "/",
		HttpOnly: true,
		Secure:   a.cfg.SessionCookieSecure,
		SameSite: http.SameSiteLaxMode,
		Expires:  expires,
		MaxAge:   int(time.Until(expires).Seconds()),
	})
}

func (a *API) clearSessionCookie(w http.ResponseWriter) {
	http.SetCookie(w, &http.Cookie{
		Name:     a.cfg.SessionCookieName,
		Value:    "",
		Path:     "/",
		HttpOnly: true,
		Secure:   a.cfg.SessionCookieSecure,
		SameSite: http.SameSiteLaxMode,
		MaxAge:   -1,
	})
}

func (a *API) sessionTokenFrom(r *http.Request) string {
	c, err := r.Cookie(a.cfg.SessionCookieName)
	if err != nil {
		return ""
	}
	return c.Value
}

func clientIP(r *http.Request) *netip.Addr {
	host, _, err := net.SplitHostPort(r.RemoteAddr)
	if err != nil {
		host = r.RemoteAddr
	}
	addr, err := netip.ParseAddr(host)
	if err != nil {
		return nil
	}
	return &addr
}
