package httpapi_test

import (
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"

	"github.com/google/uuid"

	"mawta-server/internal/chattoken"
	"mawta-server/internal/config"
	"mawta-server/internal/dbtest"
)

const chatTokenPath = "/api/v1/auth/chat-token"

// withChatKey configures a fresh signing key and returns its issuer, whose
// public key verifies what the API signs.
func withChatKey(t *testing.T) (func(*config.Config), *chattoken.Issuer) {
	t.Helper()
	seed, _, err := chattoken.GenerateKey()
	if err != nil {
		t.Fatalf("generate key: %v", err)
	}
	issuer, err := chattoken.NewIssuer(seed, "k-test", time.Hour)
	if err != nil {
		t.Fatalf("new issuer: %v", err)
	}
	return func(c *config.Config) {
		c.ChatTokenSigningKey = seed
		c.ChatTokenKeyID = "k-test"
		c.ChatTokenTTL = time.Hour
	}, issuer
}

// directorSession logs the test director in through the login endpoint and
// returns the session cookie value.
func directorSession(t *testing.T, h http.Handler) string {
	t.Helper()
	w := postLogin(t, h, directorUsername, testPassword)
	if w.Code != http.StatusOK {
		t.Fatalf("director login: got %d (%s)", w.Code, strings.TrimSpace(w.Body.String()))
	}
	for _, c := range w.Result().Cookies() {
		if c.Name == cookieName {
			return c.Value
		}
	}
	t.Fatal("no session cookie was set")
	return ""
}

func TestChatTokenForADirector(t *testing.T) {
	env := dbtest.Setup(t)
	option, issuer := withChatKey(t)
	h := newAPI(t, env, option)
	userID := insertDirector(t, env)

	w := do(t, h, directorSession(t, h), "GET", chatTokenPath, "")
	if w.Code != http.StatusOK {
		t.Fatalf("got %d (%s), want 200", w.Code, strings.TrimSpace(w.Body.String()))
	}
	if got := w.Header().Get("Cache-Control"); got != "no-store" {
		t.Errorf("Cache-Control = %q, want no-store", got)
	}
	var body struct {
		Token     string    `json:"token"`
		ExpiresAt time.Time `json:"expires_at"`
	}
	if err := json.Unmarshal(w.Body.Bytes(), &body); err != nil {
		t.Fatalf("decode: %v", err)
	}
	if left := time.Until(body.ExpiresAt); left < 59*time.Minute || left > time.Hour {
		t.Errorf("expires_at is %v away, want about 1h", left)
	}

	claims, err := chattoken.Verify(issuer.PublicKey(), body.Token, time.Now())
	if err != nil {
		t.Fatalf("verify: %v", err)
	}
	if claims.Subject != userID.String() || claims.TenantID != env.Fx.TenantA.String() || claims.Role != "director" {
		t.Errorf("claims = %+v", claims)
	}
	if _, err := uuid.Parse(claims.ID); err != nil {
		t.Errorf("jti %q is not a UUID", claims.ID)
	}
}

func TestChatTokenIsOnlyForDirectors(t *testing.T) {
	env := dbtest.Setup(t)
	option, _ := withChatKey(t)
	h := newAPI(t, env, option)

	t.Run("a teacher", func(t *testing.T) {
		wantError(t, do(t, h, login(t, env, env.Fx.UserQuispe, env.Fx.TenantA), "GET", chatTokenPath, ""), http.StatusForbidden, "not_a_director")
	})
	t.Run("no session", func(t *testing.T) {
		w := httptest.NewRecorder()
		h.ServeHTTP(w, httptest.NewRequest("GET", chatTokenPath, nil))
		if w.Code != http.StatusUnauthorized {
			t.Errorf("got %d, want 401", w.Code)
		}
	})
}

func TestChatTokenWithoutASigningKey(t *testing.T) {
	env := dbtest.Setup(t)
	h := newAPI(t, env)
	insertDirector(t, env)

	wantError(t, do(t, h, directorSession(t, h), "GET", chatTokenPath, ""), http.StatusServiceUnavailable, "chat_unavailable")
}
