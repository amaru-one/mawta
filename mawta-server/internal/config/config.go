// Package config loads runtime configuration from the environment (and .env in dev).
package config

import (
	"fmt"
	"os"
	"strconv"
	"strings"
	"time"

	"github.com/joho/godotenv"

	"mawta-server/internal/logging"
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
	// RequestBodyCapture turns on HTTP request/response body capture in the
	// request log. OFF BY DEFAULT: bodies can carry school content about
	// minors, so capture is opt-in, and even when on it is restricted to the
	// route-and-field allowlist in internal/logging.
	RequestBodyCapture bool

	TranscribeAPIKey string
	TranscribeModel  string

	// AnthropicAPIKey enables Mawta's agents (Claude through the Anthropic
	// API). Empty is valid: the server boots, and the generation routes
	// answer agent_unavailable so the app offers manual creation only.
	AnthropicAPIKey    string
	PlanningAgentModel string
	AgentTimeout       time.Duration
	// Model prices in US dollars per million tokens, used to estimate the
	// cost recorded with each generation. Unset means unknown: tokens are
	// still recorded, cost stays zero. Never guessed in code.
	AgentPriceInputPerMTok      float64
	AgentPriceOutputPerMTok     float64
	AgentPriceCacheReadPerMTok  float64
	AgentPriceCacheWritePerMTok float64

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

		// Off unless explicitly enabled. See CapturePolicy in
		// internal/logging for what is captured when this is on.
		RequestBodyCapture: RequestBodyCaptureFromEnv(),

		// Empty is a valid default: the process must still boot without STT
		// configured. See internal/stt/SPEC.md for what happens then.
		TranscribeAPIKey: getenv("TRANSCRIBE_OPENROUTER_API_KEY", ""),
		TranscribeModel:  getenv("TRANSCRIBE_MODEL", "openai/whisper-large-v3"),

		AnthropicAPIKey:             getenv("ANTHROPIC_API_KEY", ""),
		PlanningAgentModel:          getenv("PLANNING_AGENT_MODEL", "claude-sonnet-5-5"),
		AgentTimeout:                getdur("AGENT_TIMEOUT", 90*time.Second),
		AgentPriceInputPerMTok:      getfloat("AGENT_PRICE_INPUT_PER_MTOK", 0),
		AgentPriceOutputPerMTok:     getfloat("AGENT_PRICE_OUTPUT_PER_MTOK", 0),
		AgentPriceCacheReadPerMTok:  getfloat("AGENT_PRICE_CACHE_READ_PER_MTOK", 0),
		AgentPriceCacheWritePerMTok: getfloat("AGENT_PRICE_CACHE_WRITE_PER_MTOK", 0),

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

// RequestBodyCaptureFromEnv reports whether HTTP body capture is enabled.
// It delegates to logging.RequestBodyCaptureFromEnv so the flag the logger
// bakes in and the flag Config carries can never disagree — the middleware
// reads the flag from the logger it is handed, not from Config.
func RequestBodyCaptureFromEnv() bool {
	return logging.RequestBodyCaptureFromEnv()
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

func getfloat(key string, def float64) float64 {
	v, ok := os.LookupEnv(key)
	if !ok || v == "" {
		return def
	}
	f, err := strconv.ParseFloat(v, 64)
	if err != nil || f < 0 {
		return def
	}
	return f
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
