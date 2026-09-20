package httpapi_test

import (
	"context"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"

	"yanai-server/internal/auth"
	"yanai-server/internal/dbtest"
)

// Login and session resolution: the one path that runs before a tenant is
// known, and therefore the one place where getting the ordering wrong leaks
// across schools.
//
// The fixture's password hashes are placeholders, so these tests set a real
// bcrypt hash on the user first. Cost 4 — the minimum — because this is a test
// and the default cost 12 is deliberately slow.

const testPassword = "una contraseña larga"

func setPassword(t *testing.T, env *dbtest.Env, username string) {
	t.Helper()
	hash, err := auth.HashPassword(testPassword, 4)
	if err != nil {
		t.Fatalf("hash: %v", err)
	}
	if _, err := env.Admin.Pool.Exec(context.Background(),
		`update users set password_hash = $1, failed_login_count = 0, locked_until = null where username = $2`,
		hash, username); err != nil {
		t.Fatalf("set the password: %v", err)
	}
}

func postLogin(t *testing.T, h http.Handler, username, password string) *httptest.ResponseRecorder {
	t.Helper()
	body := `{"username":"` + username + `","password":"` + password + `"}`
	r := httptest.NewRequest("POST", "/api/v1/auth/login", strings.NewReader(body))
	r.Header.Set("Content-Type", "application/json")
	w := httptest.NewRecorder()
	h.ServeHTTP(w, r)
	return w
}

func TestLoginIssuesAWorkingSession(t *testing.T) {
	env := dbtest.Setup(t)
	h := newAPI(t, env)
	setPassword(t, env, "jquispe")

	w := postLogin(t, h, "jquispe", testPassword)
	if w.Code != http.StatusOK {
		t.Fatalf("login: got %d (%s), want 200", w.Code, strings.TrimSpace(w.Body.String()))
	}

	var cookie *http.Cookie
	for _, c := range w.Result().Cookies() {
		if c.Name == cookieName {
			cookie = c
		}
	}
	if cookie == nil || cookie.Value == "" {
		t.Fatal("no session cookie was set")
	}
	if !cookie.HttpOnly {
		t.Error("the session cookie is not HttpOnly")
	}

	// The cookie actually authenticates a request.
	if got := do(t, h, cookie.Value, "GET", "/api/v1/me", ""); got.Code != http.StatusOK {
		t.Errorf("GET /me with the new session: got %d, want 200", got.Code)
	}

	t.Cleanup(func() {
		env.Admin.Pool.Exec(context.Background(), //nolint:errcheck
			`delete from user_sessions where token_hash = $1`, auth.HashSessionToken(cookie.Value))
	})
}

// A wrong password and an unknown username must be indistinguishable, or the
// endpoint becomes a way to enumerate who works at the school.
func TestLoginDoesNotRevealWhetherAUserExists(t *testing.T) {
	env := dbtest.Setup(t)
	h := newAPI(t, env)
	setPassword(t, env, "jquispe")

	wrongPassword := postLogin(t, h, "jquispe", "la contraseña equivocada")
	noSuchUser := postLogin(t, h, "nadie-en-absoluto", testPassword)

	if wrongPassword.Code != noSuchUser.Code {
		t.Errorf("status differs: wrong password %d, unknown user %d", wrongPassword.Code, noSuchUser.Code)
	}
	if a, b := errorCode(t, wrongPassword), errorCode(t, noSuchUser); a != b {
		t.Errorf("error code differs: wrong password %q, unknown user %q", a, b)
	}
	if code := errorCode(t, wrongPassword); code != "invalid_credentials" {
		t.Errorf("error code = %q, want invalid_credentials", code)
	}
}

func TestLoginRejectsAnInactiveAccountAsInvalidCredentials(t *testing.T) {
	env := dbtest.Setup(t)
	h := newAPI(t, env)
	setPassword(t, env, "mrojas")
	ctx := context.Background()

	if _, err := env.Admin.Pool.Exec(ctx,
		`update users set status = 'suspended' where username = 'mrojas'`); err != nil {
		t.Fatalf("suspend: %v", err)
	}
	t.Cleanup(func() {
		env.Admin.Pool.Exec(ctx, `update users set status = 'active' where username = 'mrojas'`) //nolint:errcheck
	})

	w := postLogin(t, h, "mrojas", testPassword)
	if w.Code != http.StatusUnauthorized {
		t.Errorf("got %d, want 401", w.Code)
	}
	// Same code as a wrong password: account state must not leak either.
	if code := errorCode(t, w); code != "invalid_credentials" {
		t.Errorf("error code = %q, want invalid_credentials — account state must not leak", code)
	}
}

func TestFailedLoginsCountTowardsLockout(t *testing.T) {
	env := dbtest.Setup(t)
	h := newAPI(t, env)
	setPassword(t, env, "jquispe")
	ctx := context.Background()

	if w := postLogin(t, h, "jquispe", "mal"); w.Code != http.StatusUnauthorized {
		t.Fatalf("got %d, want 401", w.Code)
	}

	var failures int
	if err := env.Admin.Pool.QueryRow(ctx,
		`select failed_login_count from users where username = 'jquispe'`).Scan(&failures); err != nil {
		t.Fatalf("read the counter: %v", err)
	}
	if failures != 1 {
		t.Errorf("failed_login_count = %d, want 1", failures)
	}

	t.Cleanup(func() {
		env.Admin.Pool.Exec(ctx, //nolint:errcheck
			`update users set failed_login_count = 0, locked_until = null where username = 'jquispe'`)
	})
}

// Session resolution is the other half. Each of these must fail closed.
func TestSessionResolution(t *testing.T) {
	env := dbtest.Setup(t)
	h := newAPI(t, env)
	ctx := context.Background()

	path := "/api/v1/me"

	t.Run("no cookie at all", func(t *testing.T) {
		r := httptest.NewRequest("GET", path, nil)
		w := httptest.NewRecorder()
		h.ServeHTTP(w, r)
		if w.Code != http.StatusUnauthorized {
			t.Errorf("got %d, want 401", w.Code)
		}
	})

	t.Run("a token that was never issued", func(t *testing.T) {
		if w := do(t, h, "not-a-real-token", "GET", path, ""); w.Code != http.StatusUnauthorized {
			t.Errorf("got %d, want 401", w.Code)
		}
	})

	t.Run("an expired session", func(t *testing.T) {
		token := login(t, env, env.Fx.UserQuispe, env.Fx.TenantA)
		// created_at moves too: user_sessions_expires_after_created forbids a
		// row that expired before it existed.
		if _, err := env.Admin.Pool.Exec(ctx, `
			update user_sessions
			   set created_at = now() - interval '2 hours',
			       expires_at = now() - interval '1 minute'
			 where token_hash = $1`,
			auth.HashSessionToken(token)); err != nil {
			t.Fatalf("expire: %v", err)
		}
		w := do(t, h, token, "GET", path, "")
		if w.Code != http.StatusUnauthorized {
			t.Errorf("got %d, want 401", w.Code)
		}
		if code := errorCode(t, w); code != "session_expired" {
			t.Errorf("error code = %q, want session_expired", code)
		}
	})

	t.Run("a revoked session", func(t *testing.T) {
		token := login(t, env, env.Fx.UserQuispe, env.Fx.TenantA)
		if _, err := env.Admin.Pool.Exec(ctx,
			`update user_sessions set revoked_at = now(), revoked_reason = 'logout' where token_hash = $1`,
			auth.HashSessionToken(token)); err != nil {
			t.Fatalf("revoke: %v", err)
		}
		if w := do(t, h, token, "GET", path, ""); w.Code != http.StatusUnauthorized {
			t.Errorf("got %d, want 401", w.Code)
		}
	})
}

// Logout revokes server-side, not just in the browser: a stolen cookie must
// stop working the moment its owner logs out.
func TestLogoutRevokesTheSessionServerSide(t *testing.T) {
	env := dbtest.Setup(t)
	h := newAPI(t, env)
	token := login(t, env, env.Fx.UserQuispe, env.Fx.TenantA)

	if w := do(t, h, token, "GET", "/api/v1/me", ""); w.Code != http.StatusOK {
		t.Fatalf("the session should start valid, got %d", w.Code)
	}

	if w := do(t, h, token, "POST", "/api/v1/auth/logout", ""); w.Code >= 300 {
		t.Fatalf("logout: got %d", w.Code)
	}

	if w := do(t, h, token, "GET", "/api/v1/me", ""); w.Code != http.StatusUnauthorized {
		t.Errorf("the token still works after logout: got %d, want 401", w.Code)
	}

	var revokedReason *string
	if err := env.Admin.Pool.QueryRow(context.Background(),
		`select revoked_reason from user_sessions where token_hash = $1`,
		auth.HashSessionToken(token)).Scan(&revokedReason); err != nil {
		t.Fatalf("read: %v", err)
	}
	if revokedReason == nil || *revokedReason != "logout" {
		t.Errorf("revoked_reason = %v, want logout", revokedReason)
	}
}

// The session carries the tenant, and that is what scopes every query. A
// session resolved for one school must never return another school's rows.
//
// Note what this does NOT assert: a status code. Asking for tenant A's class
// with tenant B's session currently answers 200 with an empty list, because an
// RLS-scoped read with the wrong tenant returns no rows rather than an error —
// silence, not refusal. No data leaks, which is what matters here. Turning
// that into an explicit refusal is the job of the per-resource authorization
// guard, not of RLS.
func TestASessionOnlyEverSeesItsOwnSchool(t *testing.T) {
	env := dbtest.Setup(t)
	h := newAPI(t, env)

	floresToken := login(t, env, env.Fx.UserFlores, env.Fx.TenantB)

	w := do(t, h, floresToken, "GET", "/api/v1/classes/"+env.Fx.ClassMat5B.String()+"/students", "")
	if w.Code >= 500 {
		t.Fatalf("got %d (%s)", w.Code, strings.TrimSpace(w.Body.String()))
	}
	// Whatever the status, not one of tenant A's five students may appear.
	for _, student := range env.Fx.Students {
		if strings.Contains(w.Body.String(), student.String()) {
			t.Fatalf("a tenant B session saw tenant A's student %s", student)
		}
	}
	if strings.Contains(w.Body.String(), "Alvarez") {
		t.Fatal("a tenant B session saw a tenant A student's name")
	}
}
