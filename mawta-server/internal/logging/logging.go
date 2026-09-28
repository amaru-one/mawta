// Package logging configures structured JSON logging for mawta-server.
// It provides a slog.Logger that writes one JSON object per line to stdout,
// includes a stable service identifier, and respects the LOG_LEVEL environment
// variable.
package logging

import (
	"io"
	"log/slog"
	"os"
	"strings"
)

const ServiceName = "mawta-server"

// ParseLevel converts a level string to slog.Level.
// Valid values (case-insensitive): debug, info, warn, error.
// Invalid values return slog.LevelInfo and false.
func ParseLevel(s string) (slog.Level, bool) {
	switch strings.ToLower(s) {
	case "debug":
		return slog.LevelDebug, true
	case "info":
		return slog.LevelInfo, true
	case "warn":
		return slog.LevelWarn, true
	case "error":
		return slog.LevelError, true
	default:
		return slog.LevelInfo, false
	}
}

// NewJSONLogger creates a slog.Logger that writes JSON to w at the given level,
// with a stable "service" field set to ServiceName.
func NewJSONLogger(level slog.Level, w io.Writer) *slog.Logger {
	opts := &slog.HandlerOptions{Level: level}
	handler := slog.NewJSONHandler(w, opts)
	logger := slog.New(handler).With("service", ServiceName)
	return logger
}

// Setup reads LOG_LEVEL from the environment, parses it, and returns a JSON
// logger. If LOG_LEVEL is invalid, it falls back to info and logs a warning
// using a temporary text handler so the warning is visible before the real
// logger is configured.
func Setup() *slog.Logger {
	raw := os.Getenv("LOG_LEVEL")
	if raw == "" {
		raw = "info"
	}
	level, ok := ParseLevel(raw)
	if !ok {
		// Use a temporary text handler to warn about the invalid level
		// before the JSON logger is fully configured.
		tmp := slog.New(slog.NewTextHandler(os.Stderr, nil))
		tmp.Warn("invalid LOG_LEVEL, falling back to info", "LOG_LEVEL", raw)
		level = slog.LevelInfo
	}
	return NewJSONLogger(level, os.Stdout)
}
