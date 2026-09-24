package onboarding

import (
	"crypto/md5"

	"github.com/google/uuid"
)

// ID derives a row's primary key from what the row is, so loading the same
// file into an empty database always yields the same ids. It is exactly
// Postgres' md5('<kind>:<modular>:<key>')::uuid, which is what lets
// seed/seed_demo.sql refer to these rows in plain SQL without a lookup. The
// modular code is in the input so two schools never collide on MAT-C1.
func ID(kind, modularCode, key string) uuid.UUID {
	return uuid.UUID(md5.Sum([]byte(kind + ":" + modularCode + ":" + key)))
}
