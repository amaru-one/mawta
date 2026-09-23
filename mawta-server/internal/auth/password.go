// Package auth holds password hashing and opaque session tokens: pure
// functions, no I/O and no SQL. internal/repo/auth.go is the only caller.
package auth

import (
	"errors"

	"golang.org/x/crypto/bcrypt"
)

// MinPasswordLen is enforced on every new/changed password.
const MinPasswordLen = 10

// MaxPasswordLen is enforced rather than left to bcrypt's own behaviour:
// bcrypt silently truncates any input past 72 bytes, so two passwords that
// differ only after byte 72 would hash identically. Refusing the input is
// safer than accepting it and truncating server-side.
const MaxPasswordLen = 72

var (
	ErrPasswordMismatch = errors.New("auth: password mismatch")
	ErrPasswordLength   = errors.New("auth: password length out of range")
)

// dummyHash is a valid bcrypt hash of a fixed, never-issued string. VerifyPassword
// is always called against either a real hash or this one, so a wrong username
// and a wrong password take the same time — an unknown username is never a
// faster rejection than a known one with the wrong password.
const dummyHash = "$2a$12$T48pqD1ZahClpw8nNk/DU.MUNp8TVf134friFNGqQHtmj3SubxPzm"

// HashPassword hashes password at the given bcrypt cost. Rejects a password
// outside [MinPasswordLen, MaxPasswordLen] rather than truncating or padding it.
func HashPassword(password string, cost int) (string, error) {
	if err := ValidatePassword(password); err != nil {
		return "", err
	}
	hash, err := bcrypt.GenerateFromPassword([]byte(password), cost)
	if err != nil {
		return "", err
	}
	return string(hash), nil
}

// VerifyPassword reports whether password matches hash. Returns
// ErrPasswordMismatch (never a bcrypt-internal error) on any non-match, so
// callers can't distinguish "wrong password" from "malformed hash".
func VerifyPassword(hash, password string) error {
	if err := bcrypt.CompareHashAndPassword([]byte(hash), []byte(password)); err != nil {
		return ErrPasswordMismatch
	}
	return nil
}

// ValidatePassword checks length only — no composition rules (no forced
// uppercase/digit/symbol mix). Length is the one property that actually
// resists brute force; composition rules mostly just push people toward
// predictable substitutions.
func ValidatePassword(password string) error {
	if len(password) < MinPasswordLen || len(password) > MaxPasswordLen {
		return ErrPasswordLength
	}
	return nil
}

// DummyHash returns a hash to verify a submitted password against when no
// user matched the submitted username, so the login handler always does
// exactly one bcrypt comparison regardless of whether the username exists.
func DummyHash() string {
	return dummyHash
}
