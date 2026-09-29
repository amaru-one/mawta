package logging_test

import (
	"bytes"
	"context"
	"encoding/json"
	"log/slog"
	"strings"
	"testing"

	"mawta-server/internal/logging"
)

func TestParseLevel(t *testing.T) {
	tests := []struct {
		input  string
		want   slog.Level
		wantOK bool
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

// ------------------------------------------------------------- capture flag --

func TestRequestBodyCaptureFromEnv(t *testing.T) {
	t.Setenv(logging.EnvRequestBodyCapture, "")
	if logging.RequestBodyCaptureFromEnv() {
		t.Error("capture must be off by default")
	}

	for _, v := range []string{"1", "true", "TRUE", "yes", "on", "T"} {
		t.Setenv(logging.EnvRequestBodyCapture, v)
		if !logging.RequestBodyCaptureFromEnv() {
			t.Errorf("capture must be on for %q", v)
		}
	}

	for _, v := range []string{"0", "false", "off", "no", "nonsense"} {
		t.Setenv(logging.EnvRequestBodyCapture, v)
		if logging.RequestBodyCaptureFromEnv() {
			t.Errorf("capture must be off for %q", v)
		}
	}
}

// ---------------------------------------------------------- capture policy --

const jsonCT = "application/json"

func captureRequest(t *testing.T, enabled bool, route, ct string, body string) logging.CapturedBody {
	t.Helper()
	return logging.NewCapturePolicy(enabled).CaptureRequestBody(route, ct, []byte(body))
}

// With capture off — the production default — nothing is captured, and the
// status says why. The metadata is still emitted by the middleware.
func TestCaptureDisabledByDefault(t *testing.T) {
	got := captureRequest(t, false, "/api/v1/sessions/{sessionID}/attendance/{studentID}", jsonCT, `{"status":"present"}`)
	if got.Status != logging.CaptureDisabled {
		t.Errorf("status = %q, want disabled", got.Status)
	}
	if got.Value != nil {
		t.Errorf("value = %v, want nil when capture is off", got.Value)
	}
}

// An empty body is "empty" and a captured JSON null is a captured value —
// the two are distinguishable, which is the point of the status field.
func TestEmptyBodyIsDistinctFromCapturedNull(t *testing.T) {
	empty := captureRequest(t, true, "/api/v1/sessions/{sessionID}/attendance/mark-all-present", jsonCT, "")
	if empty.Status != logging.CaptureEmpty || empty.Value != nil {
		t.Errorf("empty body: status = %q, value = %v; want empty and nil", empty.Status, empty.Value)
	}

	nullField := captureRequest(t, true, "/api/v1/sessions/{sessionID}/attendance/{studentID}", jsonCT, `{"status":null}`)
	if nullField.Status != logging.CaptureCaptured {
		t.Fatalf("status = %q, want captured", nullField.Status)
	}
	obj, ok := nullField.Value.(map[string]any)
	if !ok {
		t.Fatalf("value = %T, want map[string]any", nullField.Value)
	}
	if v, present := obj["status"]; !present || v != nil {
		t.Errorf("status field = %v (present=%v), want a present JSON null", v, present)
	}
}

// Only allowlisted fields are captured; everything else in the body is
// dropped rather than logged.
func TestOnlyAllowlistedFieldsAreCaptured(t *testing.T) {
	got := captureRequest(t, true, "/api/v1/sessions/{sessionID}/attendance/{studentID}", jsonCT,
		`{"status":"late","minutes_late":7,"note":"se fue al baño","student_id":"abc"}`)
	if got.Status != logging.CaptureCaptured {
		t.Fatalf("status = %q, want captured", got.Status)
	}
	obj, ok := got.Value.(map[string]any)
	if !ok {
		t.Fatalf("value = %T, want map", got.Value)
	}
	if obj["status"] != "late" {
		t.Errorf("status = %v, want late", obj["status"])
	}
	if obj["minutes_late"] != float64(7) {
		t.Errorf("minutes_late = %v, want 7", obj["minutes_late"])
	}
	if _, present := obj["note"]; present {
		t.Errorf("note (free text) was captured: %v", obj["note"])
	}
	if _, present := obj["student_id"]; present {
		t.Errorf("student_id (student data) was captured: %v", obj["student_id"])
	}
}

// A route not on the allowlist is omitted, whatever the body holds. The
// voice-note upload (audio), the login route (credentials) and the grade
// reads (student records) are the ones that matter most.
func TestSensitiveRoutesAreOmitted(t *testing.T) {
	for _, route := range []string{
		"/api/v1/sessions/{sessionID}/students/{studentID}/voice-notes",
		"/api/v1/auth/login",
		"/api/v1/classes/{classID}/students/{studentID}/grades",
		"/api/v1/voice-notes/{voiceNoteID}/audio",
		"/some/route/that/does/not/exist",
	} {
		got := captureRequest(t, true, route, jsonCT, `{"anything":"at all"}`)
		if got.Status != logging.CaptureOmitted {
			t.Errorf("route %s: status = %q, want omitted", route, got.Status)
		}
		if got.Value != nil {
			t.Errorf("route %s: value = %v, want nil", route, got.Value)
		}
	}
}

// Fields that are not on the route's allowlist — including nested objects
// and arrays holding denied names — are absent from the capture.
func TestNestedAndArrayRedaction(t *testing.T) {
	got := captureRequest(t, true, "/api/v1/classes/{classID}/assessments", jsonCT, `{
		"kind": "tarea",
		"value_scale": "numeric",
		"component_code": "COMP",
		"nested": {"password": "hunter2", "student_id": "s1", "ok": 1},
		"items": [{"title": "secret", "status": "a"}, {"status": "b"}]
	}`)
	if got.Status != logging.CaptureCaptured {
		t.Fatalf("status = %q, want captured", got.Status)
	}
	obj, ok := got.Value.(map[string]any)
	if !ok {
		t.Fatalf("value = %T, want map", got.Value)
	}
	for _, absent := range []string{"nested", "items", "title", "password", "student_id"} {
		if _, present := obj[absent]; present {
			t.Errorf("field %q was captured: %v", absent, obj[absent])
		}
	}
	if obj["kind"] != "tarea" {
		t.Errorf("kind = %v, want tarea", obj["kind"])
	}
	if obj["value_scale"] != "numeric" {
		t.Errorf("value_scale = %v, want numeric", obj["value_scale"])
	}
}

// The denylist is the second lock: a field that somehow reached the allowlist
// is still dropped when its name is denied.
func TestDeniedFieldsAreDroppedEvenWhenAllowlisted(t *testing.T) {
	policy := logging.CapturePolicy{
		Enabled:   true,
		MaxBytes:  logging.MaxBodyBytes,
		Allowlist: map[string][]string{"/probe": {"password", "title", "status"}},
	}
	got := policy.CaptureRequestBody("/probe", jsonCT, []byte(`{"password":"x","title":"y","status":"ok"}`))
	if got.Status != logging.CaptureCaptured {
		t.Fatalf("status = %q, want captured", got.Status)
	}
	obj := got.Value.(map[string]any)
	if v, present := obj["password"]; !present || v != nil {
		t.Errorf("password = %v (present=%v), want a present null", v, present)
	}
	if v, present := obj["title"]; !present || v != nil {
		t.Errorf("title = %v (present=%v), want a present null", v, present)
	}
	if obj["status"] != "ok" {
		t.Errorf("status = %v, want ok", obj["status"])
	}
}

// Malformed JSON is never logged: the status says invalid_json and the value
// stays null.
func TestInvalidJSONIsNeverLogged(t *testing.T) {
	got := captureRequest(t, true, "/api/v1/sessions/{sessionID}/attendance/{studentID}", jsonCT, `{"status": "broken`)
	if got.Status != logging.CaptureInvalidJSON {
		t.Errorf("status = %q, want invalid_json", got.Status)
	}
	if got.Value != nil {
		t.Errorf("value = %v, want nil for malformed JSON", got.Value)
	}
}

// A body over the bound is omitted as too_large, never truncated.
func TestOversizedBodyIsTooLargeNotTruncated(t *testing.T) {
	big := `{"status":"` + strings.Repeat("x", logging.MaxBodyBytes) + `"}`
	got := captureRequest(t, true, "/api/v1/sessions/{sessionID}/attendance/{studentID}", jsonCT, big)
	if got.Status != logging.CaptureTooLarge {
		t.Errorf("status = %q, want too_large", got.Status)
	}
	if got.Value != nil {
		t.Errorf("value = %v, want nil for an oversized body", got.Value)
	}
}

// Non-JSON content types — multipart audio uploads above all — are omitted.
func TestNonJSONContentTypeIsOmitted(t *testing.T) {
	for _, ct := range []string{
		"multipart/form-data; boundary=abc",
		"audio/mpeg",
		"text/plain",
		"",
	} {
		got := captureRequest(t, true, "/api/v1/sessions/{sessionID}/attendance/{studentID}", ct, `{"status":"present"}`)
		if got.Status != logging.CaptureOmitted {
			t.Errorf("content type %q: status = %q, want omitted", ct, got.Status)
		}
	}
}

// A bare JSON scalar is not a body this policy describes.
func TestBareScalarBodyIsOmitted(t *testing.T) {
	for _, body := range []string{`"just a string"`, `42`, `true`, `[]`, `[1,2]`} {
		got := captureRequest(t, true, "/api/v1/sessions/{sessionID}/attendance/{studentID}", jsonCT, body)
		if got.Status != logging.CaptureOmitted {
			t.Errorf("body %q: status = %q, want omitted", body, got.Status)
		}
	}
}

// The response direction uses the same allowlist and the same statuses.
func TestCaptureResponseBodyMirrorsRequestRules(t *testing.T) {
	policy := logging.NewCapturePolicy(true)

	binary := policy.CaptureResponseBody("/api/v1/voice-notes/{voiceNoteID}/audio", "audio/mpeg", []byte("ID3\x04binary"))
	if binary.Status != logging.CaptureOmitted {
		t.Errorf("binary response: status = %q, want omitted", binary.Status)
	}

	empty := policy.CaptureResponseBody("/api/v1/voice-notes/{voiceNoteID}/discard", jsonCT, nil)
	if empty.Status != logging.CaptureEmpty {
		t.Errorf("empty response: status = %q, want empty", empty.Status)
	}

	off := logging.NewCapturePolicy(false).CaptureResponseBody("/api/v1/voice-notes/{voiceNoteID}/discard", jsonCT, []byte(`{}`))
	if off.Status != logging.CaptureDisabled {
		t.Errorf("capture off: status = %q, want disabled", off.Status)
	}
}

// ------------------------------------------------------------ error causes --

func TestSanitizeErrorCause(t *testing.T) {
	if got := logging.SanitizeErrorCause(nil); got != "" {
		t.Errorf("nil error = %q, want empty", got)
	}
	if got := logging.SanitizeErrorCause(errString("boom")); got != "boom" {
		t.Errorf("error = %q, want boom", got)
	}
	long := errString(strings.Repeat("a", 600))
	if got := logging.SanitizeErrorCause(long); len(got) != 500 {
		t.Errorf("long error rendered %d chars, want 500", len(got))
	}
}

type errString string

func (e errString) Error() string { return string(e) }

// ----------------------------------------------------------- worker events --

func TestJobStartEventFields(t *testing.T) {
	var buf bytes.Buffer
	logger := logging.NewJSONLogger(slog.LevelInfo, &buf)
	logging.LogJobStart(logger, logging.JobStartEvent{
		TaskID: 42, JobID: 42, Kind: "grade.recompute",
		Attempt: 1, MaxAttempts: 3, WorkerName: "w1",
	})

	var e map[string]any
	if err := json.Unmarshal(buf.Bytes(), &e); err != nil {
		t.Fatalf("parse: %v", err)
	}
	for _, k := range []string{"event", "task_id", "job_id", "kind", "attempt", "max_attempts", "worker"} {
		if _, ok := e[k]; !ok {
			t.Errorf("missing %q in %v", k, e)
		}
	}
	if e["event"] != "worker.job_started" {
		t.Errorf("event = %v, want worker.job_started", e["event"])
	}
	if e["task_id"] != float64(42) {
		t.Errorf("task_id = %v, want 42", e["task_id"])
	}
	if e["job_id"] != float64(42) {
		t.Errorf("job_id = %v, want 42", e["job_id"])
	}
}

func TestJobOutcomeEventFields(t *testing.T) {
	cases := []struct {
		outcome string
		level   string
	}{
		{logging.OutcomeSuccess, "INFO"},
		{logging.OutcomeSkipped, "INFO"},
		{logging.OutcomeRetryableFailure, "ERROR"},
		{logging.OutcomePermanentFailure, "ERROR"},
	}
	for _, tc := range cases {
		var buf bytes.Buffer
		logger := logging.NewJSONLogger(slog.LevelInfo, &buf)
		logging.LogJobOutcome(logger, logging.JobOutcomeEvent{
			TaskID: 7, JobID: 7, Kind: "voice_note.transcribe",
			Attempt: 2, MaxAttempts: 20, WorkerName: "w1",
			Outcome: tc.outcome, Reason: "handler_error",
			DurationMs: 12, Error: "boom",
		})

		var e map[string]any
		if err := json.Unmarshal(buf.Bytes(), &e); err != nil {
			t.Fatalf("parse: %v", err)
		}
		if e["level"] != tc.level {
			t.Errorf("outcome %s: level = %v, want %s", tc.outcome, e["level"], tc.level)
		}
		if e["outcome"] != tc.outcome {
			t.Errorf("outcome = %v, want %s", e["outcome"], tc.outcome)
		}
		for _, k := range []string{"task_id", "job_id", "kind", "attempt", "max_attempts", "worker", "duration_ms", "reason", "error"} {
			if _, ok := e[k]; !ok {
				t.Errorf("outcome %s: missing %q in %v", tc.outcome, k, e)
			}
		}
	}
}

// ------------------------------------------------------------- STT usage ----

func TestSTTUsageEventCostAccounting(t *testing.T) {
	zero := 0.0
	cost := 0.0123
	audio := 12.5
	tokens := int64(321)

	cases := []struct {
		name       string
		cost       *float64
		wantCost   any // nil means JSON null
		wantSource string
	}{
		{name: "reported cost", cost: &cost, wantCost: 0.0123, wantSource: logging.CostSourceProvider},
		{name: "reported zero stays zero", cost: &zero, wantCost: float64(0), wantSource: logging.CostSourceProvider},
		{name: "missing usage is null with unknown source", cost: nil, wantCost: nil, wantSource: logging.CostSourceUnknown},
	}
	for _, tc := range cases {
		var buf bytes.Buffer
		logger := logging.NewJSONLogger(slog.LevelInfo, &buf)
		logging.LogSTTUsage(logger, logging.STTUsageEvent{
			TaskID: 9, Attempt: 3, Provider: "openrouter",
			Model: "openai/whisper-large-v3", GenerationID: "gen-1",
			DurationMs: 1500, Outcome: "success",
			CostUSD: tc.cost, AudioSeconds: &audio, Tokens: &tokens,
		})

		var e map[string]any
		if err := json.Unmarshal(buf.Bytes(), &e); err != nil {
			t.Fatalf("%s: parse: %v", tc.name, err)
		}
		if e["cost_usd"] != tc.wantCost {
			t.Errorf("%s: cost_usd = %v (%T), want %v", tc.name, e["cost_usd"], e["cost_usd"], tc.wantCost)
		}
		if e["cost_source"] != tc.wantSource {
			t.Errorf("%s: cost_source = %v, want %s", tc.name, e["cost_source"], tc.wantSource)
		}
		for _, k := range []string{"event", "task_id", "attempt", "provider", "model", "duration_ms", "outcome", "generation_id", "audio_seconds", "tokens"} {
			if _, ok := e[k]; !ok {
				t.Errorf("%s: missing %q in %v", tc.name, k, e)
			}
		}
		if e["event"] != "stt.usage" {
			t.Errorf("%s: event = %v, want stt.usage", tc.name, e["event"])
		}
	}
}

// A usage event never carries the things it must never carry.
func TestSTTUsageEventNeverCarriesAudioOrTranscript(t *testing.T) {
	var buf bytes.Buffer
	logger := logging.NewJSONLogger(slog.LevelInfo, &buf)
	logging.LogSTTUsage(logger, logging.STTUsageEvent{
		TaskID: 1, Attempt: 1, Provider: "openrouter", Model: "m",
		Outcome: "success", DurationMs: 10,
	})

	// Check the event's fields, not the raw line: the message itself says
	// "transcription usage", which is fine.
	line := buf.String()
	var event map[string]any
	if err := json.Unmarshal([]byte(line), &event); err != nil {
		t.Fatalf("usage event is not one JSON object: %v: %s", err, line)
	}
	for _, banned := range []string{"transcript", "transcription", "text", "audio", "audio_data", "input_audio", "data"} {
		if _, present := event[banned]; present {
			t.Errorf("usage event carries field %q: %s", banned, line)
		}
	}
	if strings.Contains(line, "base64") {
		t.Errorf("usage event mentions base64: %s", line)
	}
}

// ------------------------------------------------------- STT task context ---

func TestSTTTaskContextRoundTrip(t *testing.T) {
	ctx := context.Background()
	if _, ok := logging.STTTaskFrom(ctx); ok {
		t.Fatal("an empty context must not carry a task")
	}
	ctx = logging.WithSTTTask(ctx, logging.STTTask{TaskID: 5, Attempt: 2})
	task, ok := logging.STTTaskFrom(ctx)
	if !ok || task.TaskID != 5 || task.Attempt != 2 {
		t.Errorf("task = %+v (ok=%v), want {5 2}", task, ok)
	}
}
