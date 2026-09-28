package logging_test

import (
	"bytes"
	"encoding/json"
	"log/slog"
	"strings"
	"testing"

	"mawta-server/internal/logging"
)

func TestParseLevel(t *testing.T) {
	tests := []struct {
		input   string
		want    slog.Level
		wantOK  bool
	}{
		{"debug", slog.LevelDebug, true},
		{"info", slog.LevelInfo, true},
		{"warn", slog.LevelWarn, true},
		{"error", slog.LevelError, true},
		{"DEBUG", slog.LevelDebug, true},
		{"Info", slog.LevelInfo, true},
		{"", slog.LevelInfo, false},
		{"verbose", slog.LevelInfo, false},
		{"trace", slog.LevelInfo, false},
	}
	for _, tt := range tests {
		got, ok := logging.ParseLevel(tt.input)
		if got != tt.want || ok != tt.wantOK {
			t.Errorf("ParseLevel(%q) = (%v, %v), want (%v, %v)", tt.input, got, ok, tt.want, tt.wantOK)
		}
	}
}

func TestNewJSONLoggerOutputsValidJSON(t *testing.T) {
	var buf bytes.Buffer
	logger := logging.NewJSONLogger(slog.LevelInfo, &buf)
	logger.Info("hello", "key", "value")

	line := strings.TrimSpace(buf.String())
	if line == "" {
		t.Fatal("expected JSON output, got empty string")
	}
	var entry map[string]any
	if err := json.Unmarshal([]byte(line), &entry); err != nil {
		t.Fatalf("output is not valid JSON: %v\noutput: %s", err, line)
	}
}

func TestNewJSONLoggerRequiredFields(t *testing.T) {
	var buf bytes.Buffer
	logger := logging.NewJSONLogger(slog.LevelInfo, &buf)
	logger.Info("test message")

	var entry map[string]any
	line := strings.TrimSpace(buf.String())
	if err := json.Unmarshal([]byte(line), &entry); err != nil {
		t.Fatalf("parse: %v", err)
	}

	// Check required fields: time, level, msg, service
	for _, key := range []string{"time", "level", "msg", "service"} {
		if _, ok := entry[key]; !ok {
			t.Errorf("missing required field %q in log entry: %v", key, entry)
		}
	}
	if entry["service"] != logging.ServiceName {
		t.Errorf("service = %v, want %q", entry["service"], logging.ServiceName)
	}
	if entry["msg"] != "test message" {
		t.Errorf("msg = %v, want %q", entry["msg"], "test message")
	}
}

func TestLevelFiltering(t *testing.T) {
	var buf bytes.Buffer
	logger := logging.NewJSONLogger(slog.LevelInfo, &buf)
	logger.Debug("should not appear")
	logger.Info("should appear")

	lines := strings.Split(strings.TrimSpace(buf.String()), "\n")
	if len(lines) != 1 {
		t.Errorf("expected 1 line at info level, got %d", len(lines))
	}
	var entry map[string]any
	if err := json.Unmarshal([]byte(lines[0]), &entry); err != nil {
		t.Fatalf("parse: %v", err)
	}
	if entry["msg"] != "should appear" {
		t.Errorf("msg = %v, want %q", entry["msg"], "should appear")
	}
}

func TestLevelFilteringDebugLevel(t *testing.T) {
	var buf bytes.Buffer
	logger := logging.NewJSONLogger(slog.LevelDebug, &buf)
	logger.Debug("debug msg")
	logger.Info("info msg")

	lines := strings.Split(strings.TrimSpace(buf.String()), "\n")
	if len(lines) != 2 {
		t.Errorf("expected 2 lines at debug level, got %d: %s", len(lines), buf.String())
	}
}

func TestOneLinePerEntry(t *testing.T) {
	var buf bytes.Buffer
	logger := logging.NewJSONLogger(slog.LevelInfo, &buf)
	logger.Info("first")
	logger.Info("second")

	output := buf.String()
	lines := strings.Split(strings.TrimSpace(output), "\n")
	if len(lines) != 2 {
		t.Errorf("expected 2 lines, got %d", len(lines))
	}
	for i, line := range lines {
		var entry map[string]any
		if err := json.Unmarshal([]byte(line), &entry); err != nil {
			t.Errorf("line %d is not valid JSON: %v\n%s", i, err, line)
		}
	}
}
