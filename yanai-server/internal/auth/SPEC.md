## Purpose
Password hashing and opaque session tokens. Pure functions only — no I/O, no SQL, no knowledge of `users` or `user_sessions`. `internal/repo/auth.go` is the only caller.

## Contents
- `password.go` — `MinPasswordLen`/`MaxPasswordLen`, `HashPassword(password, cost)`, `VerifyPassword(hash, password)` (returns `ErrPasswordMismatch` on any non-match, never a bcrypt-internal error), `ValidatePassword(password)`, `DummyHash()`.
- `token.go` — `NewSessionToken()` (32 bytes of `crypto/rand`, base64url, plus its sha256), `HashSessionToken(token)`.

## Inputs / Outputs
Input: a plaintext password or a raw session token. Output: a bcrypt hash string, or a token + its sha256. Never logs, returns, or otherwise exposes a hash or a raw token outside this package's return values.

## Conventions & Constraints
- **bcrypt, not argon2id — a deliberate choice for this repo.** `x/crypto/bcrypt` is two function calls with the cost encoded in the hash string itself, so there is nothing to store or tune separately. `x/crypto/argon2` is a raw KDF: using it for argon2id means hand-rolling salt generation, the `$argon2id$v=19$m=,t=,p=$...` encoding, parameter parsing, and a constant-time compare — on the order of 80 lines of security-critical code, in a repo whose only CI gate is `go vet` + `go build` and that has no test suite at all. Untested hand-rolled crypto encoding is the worse risk. Revisit only if a real test suite exists first.
- `MaxPasswordLen` is 72 because bcrypt silently truncates any input past 72 bytes; `HashPassword`/`ValidatePassword` refuse a longer password rather than accept the truncation silently.
- The login handler must always call `VerifyPassword` exactly once per attempt — against a real hash when the username matched, against `DummyHash()` when it didn't — so a wrong username and a wrong password take the same time and a caller can't time-distinguish "no such account" from "wrong password".
- No composition rules (forced uppercase/digit/symbol) — length is the property that actually resists brute force.

## Open Questions
- None.
