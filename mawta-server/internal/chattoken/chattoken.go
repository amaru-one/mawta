// Package chattoken issues the short-lived token a director's browser hands
// to the chat service (mawta-chat). Go only signs, with an Ed25519 private
// key; the chat service holds only the public key, so it can check a token
// but never mint one.
//
// The token is a compact JWS (a JWT): header {"alg":"EdDSA","typ":"JWT",
// "kid":…}, the Claims below, and an Ed25519 signature, each part
// base64url-encoded without padding.
package chattoken

import (
	"crypto/ed25519"
	"crypto/rand"
	"encoding/base64"
	"encoding/json"
	"errors"
	"fmt"
	"strings"
	"time"

	"github.com/google/uuid"
)

const (
	// TokenIssuer and TokenAudience are the iss and aud of every token.
	TokenIssuer   = "mawta-server"
	TokenAudience = "mawta-chat"

	algorithm = "EdDSA"
)

var b64 = base64.RawURLEncoding

// Claims is the token payload.
type Claims struct {
	Issuer   string `json:"iss"`
	Audience string `json:"aud"`
	Subject  string `json:"sub"` // users.id
	TenantID string `json:"tenant_id"`
	Role     string `json:"role"`
	IssuedAt int64  `json:"iat"`
	Expires  int64  `json:"exp"`
	ID       string `json:"jti"`
}

type header struct {
	Alg string `json:"alg"`
	Typ string `json:"typ"`
	Kid string `json:"kid"`
}

// Issuer signs tokens with one key.
type Issuer struct {
	key   ed25519.PrivateKey
	keyID string
	ttl   time.Duration
}

// NewIssuer builds an Issuer from a base64 (standard encoding) 32-byte
// Ed25519 seed, the key id that goes in the token header, and the token
// lifetime. Errors never include the seed.
func NewIssuer(seedB64, keyID string, ttl time.Duration) (*Issuer, error) {
	seed, err := base64.StdEncoding.DecodeString(strings.TrimSpace(seedB64))
	if err != nil {
		return nil, errors.New("chattoken: the signing key is not valid base64")
	}
	if len(seed) != ed25519.SeedSize {
		return nil, fmt.Errorf("chattoken: the signing key must be %d bytes, got %d", ed25519.SeedSize, len(seed))
	}
	if strings.TrimSpace(keyID) == "" {
		return nil, errors.New("chattoken: a key id is required")
	}
	if ttl <= 0 {
		return nil, errors.New("chattoken: the token lifetime must be positive")
	}
	return &Issuer{key: ed25519.NewKeyFromSeed(seed), keyID: strings.TrimSpace(keyID), ttl: ttl}, nil
}

// PublicKey is the key the chat service verifies with.
func (i *Issuer) PublicKey() ed25519.PublicKey {
	return i.key.Public().(ed25519.PublicKey)
}

// Issue signs a token for one user acting in one tenant.
func (i *Issuer) Issue(userID, tenantID uuid.UUID, role string, now time.Time) (string, time.Time, error) {
	expires := now.Add(i.ttl).Truncate(time.Second)
	h, err := json.Marshal(header{Alg: algorithm, Typ: "JWT", Kid: i.keyID})
	if err != nil {
		return "", time.Time{}, err
	}
	c, err := json.Marshal(Claims{
		Issuer:   TokenIssuer,
		Audience: TokenAudience,
		Subject:  userID.String(),
		TenantID: tenantID.String(),
		Role:     role,
		IssuedAt: now.Unix(),
		Expires:  expires.Unix(),
		ID:       uuid.NewString(),
	})
	if err != nil {
		return "", time.Time{}, err
	}
	signingInput := b64.EncodeToString(h) + "." + b64.EncodeToString(c)
	signature := ed25519.Sign(i.key, []byte(signingInput))
	return signingInput + "." + b64.EncodeToString(signature), expires.UTC(), nil
}

// Verify checks a token against a public key and returns its claims. Mawta
// itself never accepts these tokens; Verify pins down the exact format the
// chat service must check (algorithm, signature, iss, aud, exp), and the
// tests use it.
func Verify(publicKey ed25519.PublicKey, token string, now time.Time) (Claims, error) {
	parts := strings.Split(token, ".")
	if len(parts) != 3 {
		return Claims{}, errors.New("chattoken: malformed token")
	}
	rawHeader, err := b64.DecodeString(parts[0])
	if err != nil {
		return Claims{}, errors.New("chattoken: malformed header")
	}
	var h header
	if err := json.Unmarshal(rawHeader, &h); err != nil || h.Alg != algorithm {
		return Claims{}, errors.New("chattoken: unexpected algorithm")
	}
	signature, err := b64.DecodeString(parts[2])
	if err != nil || !ed25519.Verify(publicKey, []byte(parts[0]+"."+parts[1]), signature) {
		return Claims{}, errors.New("chattoken: bad signature")
	}
	rawClaims, err := b64.DecodeString(parts[1])
	if err != nil {
		return Claims{}, errors.New("chattoken: malformed claims")
	}
	var c Claims
	if err := json.Unmarshal(rawClaims, &c); err != nil {
		return Claims{}, errors.New("chattoken: malformed claims")
	}
	if c.Issuer != TokenIssuer || c.Audience != TokenAudience {
		return Claims{}, errors.New("chattoken: wrong issuer or audience")
	}
	if now.Unix() >= c.Expires {
		return Claims{}, errors.New("chattoken: token expired")
	}
	return c, nil
}

// GenerateKey mints a new key pair: the base64 seed for mawta-server and the
// base64 raw public key for the chat service (both standard encoding).
func GenerateKey() (seedB64, publicB64 string, err error) {
	public, private, err := ed25519.GenerateKey(rand.Reader)
	if err != nil {
		return "", "", err
	}
	return base64.StdEncoding.EncodeToString(private.Seed()), base64.StdEncoding.EncodeToString(public), nil
}
