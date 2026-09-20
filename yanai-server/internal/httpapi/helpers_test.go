package httpapi_test

import (
	"context"
	"encoding/json"
	"io"
	"log/slog"
	"net/http"
	"net/http/httptest"
	"os"
	"strings"
	"testing"
	"time"

	"github.com/google/uuid"

	"yanai-server/internal/auth"
	"yanai-server/internal/config"
	"yanai-server/internal/dbtest"
	"yanai-server/internal/httpapi"
)

func TestMain(m *testing.M) { os.Exit(dbtest.Main(m)) }

const cookieName = "yanai_session"

// newAPI builds the real router over the test database. Handlers are exercised
// through it rather than called directly, so middleware, routing and error
// mapping are all in the path — which is where several of the behaviours under
// test actually live.
func newAPI(t *testing.T, env *dbtest.Env) http.Handler {
	t.Helper()
	cfg := config.Config{
		SessionCookieName:   cookieName,
		SessionCookieSecure: false,
		// Real durations, not the zero value: sessionAuth treats
		// now - last_seen_at > SessionIdleTimeout as idle, so a zero timeout
		// revokes every session on its first request.
		SessionTTL:         time.Hour,
		SessionIdleTimeout: time.Hour,
		LoginMaxFailures:   8,
		LoginLockout:       15 * time.Minute,
		BcryptCost:         4, // the minimum; the default 12 is deliberately slow
		StorageDir:         t.TempDir(),
	}
	return httpapi.New(env.App, cfg, slog.New(slog.NewTextHandler(io.Discard, nil))).Router()
}

// login mints a real session row for a user and returns its cookie value.
// It writes through the admin pool because user_sessions carries no RLS policy
// and this is fixture work, not the thing under test. Tests that need the
// login *endpoint* exercised call it directly instead — see auth_test.go.
func login(t *testing.T, env *dbtest.Env, userID, tenantID uuid.UUID) string {
	t.Helper()
	ctx := context.Background()

	token, hash, err := auth.NewSessionToken()
	if err != nil {
		t.Fatalf("mint a session token: %v", err)
	}

	var membershipID uuid.UUID
	if err := env.Admin.Pool.QueryRow(ctx,
		`select id from memberships where user_id = $1 and tenant_id = $2 and deleted_at is null`,
		userID, tenantID).Scan(&membershipID); err != nil {
		t.Fatalf("find the membership: %v", err)
	}

	if _, err := env.Admin.Pool.Exec(ctx, `
		insert into user_sessions (token_hash, user_id, tenant_id, membership_id, role, expires_at)
		values ($1, $2, $3, $4, 'teacher', now() + interval '1 hour')`,
		hash, userID, tenantID, membershipID); err != nil {
		t.Fatalf("create the session: %v", err)
	}
	t.Cleanup(func() {
		env.Admin.Pool.Exec(ctx, `delete from user_sessions where token_hash = $1`, hash) //nolint:errcheck
	})

	return token
}

func do(t *testing.T, h http.Handler, token, method, path, body string) *httptest.ResponseRecorder {
	t.Helper()
	var r *http.Request
	if body == "" {
		r = httptest.NewRequest(method, path, nil)
	} else {
		r = httptest.NewRequest(method, path, strings.NewReader(body))
		r.Header.Set("Content-Type", "application/json")
	}
	r.AddCookie(&http.Cookie{Name: cookieName, Value: token})
	w := httptest.NewRecorder()
	h.ServeHTTP(w, r)
	return w
}

// errorCode pulls the machine-readable code out of an error response,
// accepting either the nested or flat shape so a test asserts on the code
// rather than on the envelope.
func errorCode(t *testing.T, w *httptest.ResponseRecorder) string {
	t.Helper()
	var payload struct {
		Error struct {
			Code string `json:"code"`
		} `json:"error"`
		Code string `json:"code"`
	}
	if err := json.Unmarshal(w.Body.Bytes(), &payload); err != nil {
		return ""
	}
	if payload.Error.Code != "" {
		return payload.Error.Code
	}
	return payload.Code
}

// route is one entry in a table of requests.
type route struct {
	name   string
	method string
	path   string
	body   string
}
