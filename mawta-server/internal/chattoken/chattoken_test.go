package chattoken_test

import (
	"crypto/ed25519"
	"encoding/base64"
	"encoding/json"
	"strings"
	"testing"
	"time"

	"github.com/google/uuid"

	"mawta-server/internal/chattoken"
)

func newIssuer(t *testing.T) *chattoken.Issuer {
	t.Helper()
	seed, _, err := chattoken.GenerateKey()
	if err != nil {
		t.Fatalf("generate key: %v", err)
	}
	issuer, err := chattoken.NewIssuer(seed, "k1", time.Hour)
	if err != nil {
		t.Fatalf("new issuer: %v", err)
	}
	return issuer
}

func TestIssueProducesAVerifiableToken(t *testing.T) {
	issuer := newIssuer(t)
	user, tenant := uuid.New(), uuid.New()
	now := time.Date(2026, 10, 15, 10, 0, 0, 0, time.UTC)

	token, expires, err := issuer.Issue(user, tenant, "director", now)
	if err != nil {
		t.Fatalf("issue: %v", err)
	}
	if want := now.Add(time.Hour); !expires.Equal(want) {
		t.Errorf("expires = %v, want %v", expires, want)
	}

	claims, err := chattoken.Verify(issuer.PublicKey(), token, now.Add(time.Minute))
	if err != nil {
		t.Fatalf("verify: %v", err)
	}
	if claims.Subject != user.String() || claims.TenantID != tenant.String() || claims.Role != "director" {
		t.Errorf("claims = %+v", claims)
	}
	if claims.Issuer != "mawta-server" || claims.Audience != "mawta-chat" {
		t.Errorf("iss/aud = %q/%q", claims.Issuer, claims.Audience)
	}
	if claims.IssuedAt != now.Unix() || claims.Expires != now.Add(time.Hour).Unix() {
		t.Errorf("iat/exp = %d/%d", claims.IssuedAt, claims.Expires)
	}

	rawHeader, err := base64.RawURLEncoding.DecodeString(strings.Split(token, ".")[0])
	if err != nil {
		t.Fatalf("decode header: %v", err)
	}
	var h map[string]string
	if err := json.Unmarshal(rawHeader, &h); err != nil {
		t.Fatalf("unmarshal header: %v", err)
	}
	if h["alg"] != "EdDSA" || h["typ"] != "JWT" || h["kid"] != "k1" {
		t.Errorf("header = %v", h)
	}
}

func TestEveryTokenHasItsOwnID(t *testing.T) {
	issuer := newIssuer(t)
	now := time.Now()
	a, _, _ := issuer.Issue(uuid.New(), uuid.New(), "director", now)
	b, _, _ := issuer.Issue(uuid.New(), uuid.New(), "director", now)
	ca, _ := chattoken.Verify(issuer.PublicKey(), a, now)
	cb, _ := chattoken.Verify(issuer.PublicKey(), b, now)
	if ca.ID == "" || ca.ID == cb.ID {
		t.Errorf("jti not unique: %q and %q", ca.ID, cb.ID)
	}
}

func TestVerifyRejectsBadTokens(t *testing.T) {
	issuer := newIssuer(t)
	now := time.Now()
	token, _, err := issuer.Issue(uuid.New(), uuid.New(), "director", now)
	if err != nil {
		t.Fatalf("issue: %v", err)
	}
	parts := strings.Split(token, ".")
	forged, _ := json.Marshal(chattoken.Claims{Issuer: "mawta-server", Audience: "mawta-chat", Subject: uuid.NewString(), Role: "director", Expires: now.Add(time.Hour).Unix()})
	other := newIssuer(t)
	cases := map[string]struct {
		key   ed25519.PublicKey
		token string
		at    time.Time
	}{
		"tampered claims": {issuer.PublicKey(), parts[0] + "." + base64.RawURLEncoding.EncodeToString(forged) + "." + parts[2], now},
		"another key":     {other.PublicKey(), token, now},
		"expired":         {issuer.PublicKey(), token, now.Add(2 * time.Hour)},
		"malformed":       {issuer.PublicKey(), "not.a-token", now},
	}
	for name, c := range cases {
		if _, err := chattoken.Verify(c.key, c.token, c.at); err == nil {
			t.Errorf("%s: verified, want an error", name)
		}
	}
}

func TestNewIssuerRejectsBadInput(t *testing.T) {
	seed, _, _ := chattoken.GenerateKey()
	cases := map[string]struct {
		seed, kid string
		ttl       time.Duration
	}{
		"not base64":   {"%%%", "k1", time.Hour},
		"wrong length": {base64.StdEncoding.EncodeToString([]byte("short")), "k1", time.Hour},
		"no key id":    {seed, " ", time.Hour},
		"no lifetime":  {seed, "k1", 0},
	}
	for name, c := range cases {
		if _, err := chattoken.NewIssuer(c.seed, c.kid, c.ttl); err == nil {
			t.Errorf("%s: accepted, want an error", name)
		} else if strings.Contains(err.Error(), seed) {
			t.Errorf("%s: the error leaks the key", name)
		}
	}
}
