package httpapi_test

import (
	"context"
	"net/http"
	"strings"
	"testing"

	"github.com/google/uuid"

	"mawta-server/internal/dbtest"
)

// A director logs in without a teacher profile, reads /me, and is kept out
// of every teacher route.
func TestDirectorLogsInWithoutATeacherProfile(t *testing.T) {
	env := dbtest.Setup(t)
	h := newAPI(t, env)
	ctx := context.Background()

	var userID uuid.UUID
	if err := env.Admin.Pool.QueryRow(ctx, `
		insert into users (email, given_name, family_name, display_name, username, password_hash, password_changed_at)
		values ('directora@example.com', 'Rosa', 'Huamán', 'Rosa Huamán', 'rhuaman-directora', 'x', now())
		returning id`).Scan(&userID); err != nil {
		t.Fatalf("insert user: %v", err)
	}
	t.Cleanup(func() {
		for _, q := range []string{
			`delete from user_sessions where user_id = $1`,
			`delete from memberships where user_id = $1`,
			`delete from users where id = $1`,
		} {
			env.Admin.Pool.Exec(context.Background(), q, userID) //nolint:errcheck
		}
	})
	if _, err := env.Admin.Pool.Exec(ctx, `
		insert into memberships (tenant_id, user_id, role, status, joined_at)
		values ($1, $2, 'director', 'active', now())`, env.Fx.TenantA, userID); err != nil {
		t.Fatalf("insert membership: %v", err)
	}
	setPassword(t, env, "rhuaman-directora")

	w := postLogin(t, h, "rhuaman-directora", testPassword)
	if w.Code != http.StatusOK {
		t.Fatalf("login: got %d (%s), want 200", w.Code, strings.TrimSpace(w.Body.String()))
	}
	if !strings.Contains(w.Body.String(), `"role":"director"`) {
		t.Errorf("login body has no director role: %s", w.Body.String())
	}
	var token string
	for _, c := range w.Result().Cookies() {
		if c.Name == cookieName {
			token = c.Value
		}
	}
	if token == "" {
		t.Fatal("no session cookie was set")
	}

	if got := do(t, h, token, "GET", "/api/v1/me", ""); got.Code != http.StatusOK {
		t.Errorf("GET /me: got %d (%s), want 200", got.Code, strings.TrimSpace(got.Body.String()))
	}
	home := do(t, h, token, "GET", "/api/v1/home", "")
	if home.Code != http.StatusForbidden {
		t.Errorf("GET /home: got %d, want 403", home.Code)
	}
	if code := errorCode(t, home); code != "not_a_member" {
		t.Errorf("GET /home error code = %q, want not_a_member", code)
	}
}
