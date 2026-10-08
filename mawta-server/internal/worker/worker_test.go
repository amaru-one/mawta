package worker

import (
	"encoding/json"
	"log/slog"
	"strings"
	"testing"
	"time"

	"github.com/google/uuid"
)

// captureLog runs f with a JSON handler writing to a buffer and returns
// the parsed log entries.
func captureLog(f func(logger *slog.Logger)) []map[string]any {
	var buf strings.Builder
	logger := slog.New(slog.NewJSONHandler(&buf, nil))
	f(logger)

	var entries []map[string]any
	for _, line := range strings.Split(strings.TrimSpace(buf.String()), "\n") {
		if line == "" {
			continue
		}
		var entry map[string]any
		if err := json.Unmarshal([]byte(line), &entry); err != nil {
			continue
		}
		entries = append(entries, entry)
	}
	return entries
}

func TestJobSuccessLogFields(t *testing.T) {
	job := Job{
		ID:          42,
		TenantID:    uuid.Nil,
		Kind:        "voice_note.transcribe",
		Payload:     []byte(`{"student_id":"abc"}`),
		Attempts:    1,
		MaxAttempts: 3,
	}

	entries := captureLog(func(logger *slog.Logger) {
		durationMs := time.Since(time.Now()).Milliseconds()
		logger.Info("worker: job completed",
			"job_id", job.ID,
			"kind", job.Kind,
			"attempt", job.Attempts,
			"duration_ms", durationMs,
		)
	})

	if len(entries) != 1 {
		t.Fatalf("expected 1 log entry, got %d", len(entries))
	}
	entry := entries[0]

	for _, key := range []string{"job_id", "kind", "attempt", "duration_ms"} {
		if _, ok := entry[key]; !ok {
			t.Errorf("missing field %q in log entry", key)
		}
	}
	if entry["kind"] != "voice_note.transcribe" {
		t.Errorf("kind = %v, want voice_note.transcribe", entry["kind"])
	}
	if entry["msg"] != "worker: job completed" {
		t.Errorf("msg = %v, want worker: job completed", entry["msg"])
	}
}

func TestJobFailureLogFields(t *testing.T) {
	job := Job{
		ID:          99,
		TenantID:    uuid.Nil,
		Kind:        "voice_note.transcribe",
		Payload:     []byte(`{}`),
		Attempts:    3,
		MaxAttempts: 3,
	}

	entries := captureLog(func(logger *slog.Logger) {
		durationMs := time.Since(time.Now()).Milliseconds()
		logger.Error("worker: job failed",
			"job_id", job.ID,
			"kind", job.Kind,
			"attempt", job.Attempts,
			"duration_ms", durationMs,
			"error", "something broke",
		)
	})

	if len(entries) != 1 {
		t.Fatalf("expected 1 log entry, got %d", len(entries))
	}
	entry := entries[0]

	for _, key := range []string{"job_id", "kind", "attempt", "duration_ms"} {
		if _, ok := entry[key]; !ok {
			t.Errorf("missing field %q in log entry", key)
		}
	}
	if entry["kind"] != "voice_note.transcribe" {
		t.Errorf("kind = %v, want voice_note.transcribe", entry["kind"])
	}
	if entry["msg"] != "worker: job failed" {
		t.Errorf("msg = %v, want worker: job failed", entry["msg"])
	}
}

func TestJobPayloadNotLogged(t *testing.T) {
	job := Job{
		ID:          1,
		TenantID:    uuid.Nil,
		Kind:        "test.kind",
		Payload:     []byte(`{"secret":"should not appear"}`),
		Attempts:    1,
		MaxAttempts: 3,
	}

	var buf strings.Builder
	logger := slog.New(slog.NewJSONHandler(&buf, nil))
	durationMs := time.Since(time.Now()).Milliseconds()
	logger.Info("worker: job completed",
		"job_id", job.ID,
		"kind", job.Kind,
		"attempt", job.Attempts,
		"duration_ms", durationMs,
	)

	line := strings.TrimSpace(buf.String())
	if strings.Contains(line, "secret") {
		t.Errorf("log entry contains payload data: %s", line)
	}
	if strings.Contains(line, "Payload") || strings.Contains(line, "payload") {
		t.Errorf("log entry contains payload field: %s", line)
	}
}
