// Package config loads runtime configuration from the environment (and .env in dev).
package config

import (
	"fmt"
	"os"
	"strconv"
	"strings"

	"github.com/joho/godotenv"
)

type Config struct {
	DatabaseURL       string
	HTTPAddr          string
	WorkerEnabled     bool
	WorkerConcurrency int
	WorkerQueue       string
	StorageDir        string
	CORSOrigins       []string
	LogLevel          string
}

func Load() (Config, error) {
	_ = godotenv.Load() // ignore missing .env in non-dev environments

	cfg := Config{
		DatabaseURL:       getenv("DATABASE_URL", ""),
		HTTPAddr:          getenv("HTTP_ADDR", ":8080"),
		WorkerEnabled:     getbool("WORKER_ENABLED", true),
		WorkerConcurrency: getint("WORKER_CONCURRENCY", 2),
		WorkerQueue:       getenv("WORKER_QUEUE", "default"),
		StorageDir:        getenv("STORAGE_DIR", "./data/audio"),
		CORSOrigins:       splitcsv(getenv("CORS_ORIGINS", "http://localhost:5173")),
		LogLevel:          getenv("LOG_LEVEL", "info"),
	}

	if cfg.DatabaseURL == "" {
		return cfg, fmt.Errorf("config: DATABASE_URL is required")
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
