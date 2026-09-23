// Package config loads runtime configuration from the environment (and .env in dev).
package config

import (
	"fmt"
	"os"
	"strconv"
	"strings"
	"time"

	"github.com/joho/godotenv"
)

type Config struct {
	DatabaseURL string
	// AdminDatabaseURL connects as a role with real ownership/DDL rights
	// (schema migrations) or the pre-tenant bypass cmd/useradd needs to seed
	// the very first users/memberships row (see internal/db.WithSystemTx).
	// DatabaseURL itself connects as the non-owner mawta_app role — enough
	// for cmd/api, never enough for either of those. Optional here: only
	// goose and cmd/useradd need it, cmd/api never reads it.
	AdminDatabaseURL  string
	HTTPAddr          string
	WorkerEnabled     bool
	WorkerConcurrency int
	WorkerQueue       string
	StorageDir        string
	CORSOrigins       []string
	LogLevel          string

	OpenAIAPIKey string
	STTModel     string

	SessionCookieName   string
	SessionCookieSecure bool
	SessionTTL          time.Duration
	SessionIdleTimeout  time.Duration
	LoginMaxFailures    int
	LoginLockout        time.Duration
	BcryptCost          int
}

func Load() (Config, error) {
	_ = godotenv.Load() // ignore missing .env in non-dev environments

	cfg := Config{
		DatabaseURL:       getenv("DATABASE_URL", ""),
		AdminDatabaseURL:  getenv("ADMIN_DATABASE_URL", ""),
		HTTPAddr:          getenv("HTTP_ADDR", ":8080"),
		WorkerEnabled:     getbool("WORKER_ENABLED", true),
		WorkerConcurrency: getint("WORKER_CONCURRENCY", 2),
		WorkerQueue:       getenv("WORKER_QUEUE", "default"),
		StorageDir:        getenv("STORAGE_DIR", "./data/audio"),
		CORSOrigins:       splitcsv(getenv("CORS_ORIGINS", "http://localhost:5173")),
		LogLevel:          getenv("LOG_LEVEL", "info"),

		// Empty is a valid default: the process must still boot without STT
		// configured. See internal/stt/SPEC.md for what happens then.
		OpenAIAPIKey: getenv("OPENAI_API_KEY", ""),
		STTModel:     getenv("OPENAI_TRANSCRIBE_MODEL", "gpt-4o-mini-transcribe"),

		SessionCookieName: getenv("SESSION_COOKIE_NAME", "mawta_session"),
		// Fails closed: a production deploy that forgets to set this still
		// ships Secure cookies. Dev sets SESSION_COOKIE_SECURE=false in .env
		// because Safari refuses a Secure cookie over plain http://localhost.
		SessionCookieSecure: getbool("SESSION_COOKIE_SECURE", true),
		SessionTTL:          getdur("SESSION_TTL", 720*time.Hour),
		SessionIdleTimeout:  getdur("SESSION_IDLE_TIMEOUT", 336*time.Hour),
		LoginMaxFailures:    getint("LOGIN_MAX_FAILURES", 8),
		LoginLockout:        getdur("LOGIN_LOCKOUT", 15*time.Minute),
		BcryptCost:          getint("BCRYPT_COST", 12),
	}

	if cfg.DatabaseURL == "" {
		return cfg, fmt.Errorf("config: DATABASE_URL is required")
	}

	// AllowCredentials with a wildcard origin is rejected by every browser
	// anyway, and combined with Secure cookies it's the classic CORS
	// footgun — refuse to start rather than ship a config that silently
	// can't set cookies at all.
	if cfg.SessionCookieSecure {
		for _, origin := range cfg.CORSOrigins {
			if origin == "*" {
				return cfg, fmt.Errorf("config: CORS_ORIGINS may not contain \"*\" when SESSION_COOKIE_SECURE is true")
			}
		}
	}

	return cfg, nil
}

func getenv(key, def string) string {
	if v, ok := os.LookupEnv(key); ok && v != "" {
		return v
	}
	return def
}

func getbool(key string, def bool) bool {
	v, ok := os.LookupEnv(key)
	if !ok || v == "" {
		return def
	}
	b, err := strconv.ParseBool(v)
	if err != nil {
		return def
	}
	return b
}

func getint(key string, def int) int {
	v, ok := os.LookupEnv(key)
	if !ok || v == "" {
		return def
	}
	n, err := strconv.Atoi(v)
	if err != nil {
		return def
	}
	return n
}

func getdur(key string, def time.Duration) time.Duration {
	v, ok := os.LookupEnv(key)
	if !ok || v == "" {
		return def
	}
	d, err := time.ParseDuration(v)
	if err != nil {
		return def
	}
	return d
}

func splitcsv(v string) []string {
	parts := strings.Split(v, ",")
	out := make([]string, 0, len(parts))
	for _, p := range parts {
		p = strings.TrimSpace(p)
		if p != "" {
			out = append(out, p)
		}
	}
	return out
}
