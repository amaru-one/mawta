package auth

import (
	"crypto/rand"
	"crypto/sha256"
	"encoding/base64"
	"fmt"
)

// tokenBytes is 256 bits — enough that the token itself needs no additional
// work factor when hashed for storage (see user_sessions.token_hash).
const tokenBytes = 32

// NewSessionToken mints a random session token (43-char base64url, no
// padding) and its sha256. Only the hash is ever persisted; the raw token
// is returned once, for the Set-Cookie header.
func NewSessionToken() (token string, hash []byte, err error) {
	buf := make([]byte, tokenBytes)
	if _, err := rand.Read(buf); err != nil {
		return "", nil, fmt.Errorf("auth: generate token: %w", err)
	}
	token = base64.RawURLEncoding.EncodeToString(buf)
	return token, HashSessionToken(token), nil
}

// HashSessionToken hashes a raw token for lookup/storage.
func HashSessionToken(token string) []byte {
	sum := sha256.Sum256([]byte(token))
	return sum[:]
}
