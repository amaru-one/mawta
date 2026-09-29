package stt_test

import (
	"bytes"
	"context"
	"encoding/base64"
	"encoding/json"
	"errors"
	"log/slog"
	"net/http"
	"net/http/httptest"
	"strings"
	"sync"
	"testing"

	"mawta-server/internal/logging"
	"mawta-server/internal/stt"
)

// fakeProvider is a local HTTP server standing in for OpenRouter. No test
// here can make a paid call: the client is pointed at this server, which
// answers with synthetic data.
type fakeProvider struct {
	mu       sync.Mutex
	status   int
	body     string
	requests int
}

func (f *fakeProvider) ServeHTTP(w http.ResponseWriter, r *http.Request) {
	f.mu.Lock()
	f.requests++
	status, body := f.status, f.body
	f.mu.Unlock()
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	_, _ = w.Write([]byte(body))
}

func newClient(t *testing.T, srv *httptest.Server, apiKey, model string) *stt.Client {
	t.Helper()
	c := stt.NewClient(apiKey, model)
	c.SetBaseURL(srv.URL)
	return c
}

// logBuffer installs a buffer-backed logger on the client and returns it.
func logBuffer(t *testing.T, c *stt.Client) *bytes.Buffer {
	t.Helper()
	var buf bytes.Buffer
	c.SetLogger(slog.New(slog.NewJSONHandler(&buf, nil)))
	return &buf
}

func lastEntry(t *testing.T, buf *bytes.Buffer) map[string]any {
	t.Helper()
	lines := strings.Split(strings.TrimSpace(buf.String()), "\n")
	if len(lines) == 0 || strings.TrimSpace(lines[len(lines)-1]) == "" {
		t.Fatal("no log entry was emitted")
	}
	var e map[string]any
	if err := json.Unmarshal([]byte(lines[len(lines)-1]), &e); err != nil {
		t.Fatalf("parse usage event: %v\n%s", err, lines[len(lines)-1])
	}
	return e
}

func TestTranscribeReturnsTextAndReportedUsage(t *testing.T) {
	srv := httptest.NewServer(&fakeProvider{
		status: http.StatusOK,
		body:   `{"text":"hola mundo","id":"gen-abc","usage":{"cost":0.0123,"audio_seconds":12.5,"tokens":321}}`,
	})
	defer srv.Close()

	c := newClient(t, srv, "key", "openai/whisper-large-v3")
	buf := logBuffer(t, c)

	text, usage, err := c.TranscribeWithUsage(context.Background(), []byte("fake-mp3"))
	if err != nil {
		t.Fatalf("TranscribeWithUsage: %v", err)
	}
	if text != "hola mundo" {
		t.Errorf("text = %q, want hola mundo", text)
	}
	if usage.GenerationID != "gen-abc" {
		t.Errorf("GenerationID = %q, want gen-abc", usage.GenerationID)
	}
	if usage.CostUSD == nil || *usage.CostUSD != 0.0123 {
		t.Errorf("CostUSD = %v, want 0.0123", usage.CostUSD)
	}
	if usage.AudioSeconds == nil || *usage.AudioSeconds != 12.5 {
		t.Errorf("AudioSeconds = %v, want 12.5", usage.AudioSeconds)
	}
	if usage.Tokens == nil || *usage.Tokens != 321 {
		t.Errorf("Tokens = %v, want 321", usage.Tokens)
	}

	e := lastEntry(t, buf)
	if e["event"] != "stt.usage" {
		t.Errorf("event = %v, want stt.usage", e["event"])
	}
	if e["outcome"] != "success" {
		t.Errorf("outcome = %v, want success", e["outcome"])
	}
	if e["cost_usd"] != 0.0123 {
		t.Errorf("cost_usd = %v, want 0.0123", e["cost_usd"])
	}
	if e["cost_source"] != logging.CostSourceProvider {
		t.Errorf("cost_source = %v, want provider", e["cost_source"])
	}
	if e["generation_id"] != "gen-abc" {
		t.Errorf("generation_id = %v, want gen-abc", e["generation_id"])
	}
	if e["model"] != "openai/whisper-large-v3" {
		t.Errorf("model = %v, want the requested model", e["model"])
	}
	if e["provider"] != stt.ProviderName {
		t.Errorf("provider = %v, want %s", e["provider"], stt.ProviderName)
	}
}

// A reported zero cost is a real zero, not a missing one.
func TestReportedZeroCostStaysNumericZero(t *testing.T) {
	srv := httptest.NewServer(&fakeProvider{
		status: http.StatusOK,
		body:   `{"text":"x","usage":{"cost":0}}`,
	})
	defer srv.Close()

	c := newClient(t, srv, "key", "m")
	buf := logBuffer(t, c)

	_, usage, err := c.TranscribeWithUsage(context.Background(), []byte("a"))
	if err != nil {
		t.Fatalf("TranscribeWithUsage: %v", err)
	}
	if usage.CostUSD == nil || *usage.CostUSD != 0 {
		t.Fatalf("CostUSD = %v, want a pointer to 0", usage.CostUSD)
	}

	e := lastEntry(t, buf)
	if e["cost_usd"] != float64(0) {
		t.Errorf("cost_usd = %v (%T), want numeric 0", e["cost_usd"], e["cost_usd"])
	}
	if e["cost_source"] != logging.CostSourceProvider {
		t.Errorf("cost_source = %v, want provider", e["cost_source"])
	}
}

// No usage object in the response: cost is null with cost_source=unknown.
// Nothing is invented and zero is not inferred.
func TestMissingUsageIsNullOrUnknown(t *testing.T) {
	srv := httptest.NewServer(&fakeProvider{
		status: http.StatusOK,
		body:   `{"text":"x"}`,
	})
	defer srv.Close()

	c := newClient(t, srv, "key", "m")
	buf := logBuffer(t, c)

	_, usage, err := c.TranscribeWithUsage(context.Background(), []byte("a"))
	if err != nil {
		t.Fatalf("TranscribeWithUsage: %v", err)
	}
	if usage.CostUSD != nil {
		t.Errorf("CostUSD = %v, want nil when the provider reported nothing", usage.CostUSD)
	}

	e := lastEntry(t, buf)
	if e["cost_usd"] != nil {
		t.Errorf("cost_usd = %v, want null", e["cost_usd"])
	}
	if e["cost_source"] != logging.CostSourceUnknown {
		t.Errorf("cost_source = %v, want unknown", e["cost_source"])
	}
}

// A provider failure still logs exactly one usage event, classified, with
// the cost the provider reported (here: none).
func TestProviderFailureLogsUsage(t *testing.T) {
	srv := httptest.NewServer(&fakeProvider{
		status: http.StatusBadRequest,
		body:   `{"error":{"message":"bad audio"}}`,
	})
	defer srv.Close()

	c := newClient(t, srv, "key", "m")
	buf := logBuffer(t, c)

	_, _, err := c.TranscribeWithUsage(context.Background(), []byte("a"))
	if !errors.Is(err, stt.ErrPermanent) {
		t.Fatalf("err = %v, want a permanent failure", err)
	}

	e := lastEntry(t, buf)
	if e["outcome"] != "error" {
		t.Errorf("outcome = %v, want error", e["outcome"])
	}
	if e["error_class"] != "permanent" {
		t.Errorf("error_class = %v, want permanent", e["error_class"])
	}
	if e["cost_usd"] != nil {
		t.Errorf("cost_usd = %v, want null", e["cost_usd"])
	}
	// The provider's error body must not reach the log.
	if strings.Contains(buf.String(), "bad audio") {
		t.Errorf("the provider error body reached the log: %s", buf.String())
	}
}

// A transient failure (5xx) is classified transient, not permanent.
func TestTransientFailureIsClassifiedTransient(t *testing.T) {
	srv := httptest.NewServer(&fakeProvider{status: http.StatusBadGateway, body: `{}`})
	defer srv.Close()

	c := newClient(t, srv, "key", "m")
	buf := logBuffer(t, c)

	_, _, err := c.TranscribeWithUsage(context.Background(), []byte("a"))
	if errors.Is(err, stt.ErrPermanent) {
		t.Fatal("a 5xx must not be a permanent failure")
	}
	if err == nil {
		t.Fatal("a 5xx must fail the call")
	}

	e := lastEntry(t, buf)
	if e["error_class"] != "transient" {
		t.Errorf("error_class = %v, want transient", e["error_class"])
	}
}

// A missing API key never reaches the provider, so no usage event is emitted:
// there is nothing to account.
func TestMissingAPIKeyEmitsNoUsageEvent(t *testing.T) {
	srv := httptest.NewServer(&fakeProvider{status: http.StatusOK, body: `{"text":"x"}`})
	defer srv.Close()

	c := newClient(t, srv, "", "m")
	buf := logBuffer(t, c)

	_, _, err := c.TranscribeWithUsage(context.Background(), []byte("a"))
	if !errors.Is(err, stt.ErrPermanent) {
		t.Fatalf("err = %v, want a permanent failure", err)
	}
	if buf.Len() != 0 {
		t.Errorf("a call that never reached the provider emitted a usage event: %s", buf.String())
	}
}

// The task identity from the context lands in the usage event, so a call can
// be attributed to the queue job that made it.
func TestUsageEventCarriesTaskIdentity(t *testing.T) {
	srv := httptest.NewServer(&fakeProvider{status: http.StatusOK, body: `{"text":"x","id":"g1"}`})
	defer srv.Close()

	c := newClient(t, srv, "key", "m")
	buf := logBuffer(t, c)

	ctx := logging.WithSTTTask(context.Background(), logging.STTTask{TaskID: 77, Attempt: 4})
	if _, _, err := c.TranscribeWithUsage(ctx, []byte("a")); err != nil {
		t.Fatalf("TranscribeWithUsage: %v", err)
	}

	e := lastEntry(t, buf)
	if e["task_id"] != float64(77) {
		t.Errorf("task_id = %v, want 77", e["task_id"])
	}
	if e["attempt"] != float64(4) {
		t.Errorf("attempt = %v, want 4", e["attempt"])
	}
}

// The two-value form the Transcriber interface is written against still
// works and still logs its usage event.
func TestTranscribeTwoValueFormStillLogsUsage(t *testing.T) {
	srv := httptest.NewServer(&fakeProvider{
		status: http.StatusOK,
		body:   `{"text":"hola","usage":{"cost":0.5}}`,
	})
	defer srv.Close()

	c := newClient(t, srv, "key", "m")
	buf := logBuffer(t, c)

	text, err := c.Transcribe(context.Background(), []byte("a"))
	if err != nil || text != "hola" {
		t.Fatalf("Transcribe = (%q, %v), want (hola, nil)", text, err)
	}
	e := lastEntry(t, buf)
	if e["cost_usd"] != 0.5 {
		t.Errorf("cost_usd = %v, want 0.5", e["cost_usd"])
	}
}

// The request the client sends is the base64 audio the provider expects, and
// the API key never appears in any log line.
func TestAPIKeyNeverReachesTheLog(t *testing.T) {
	var gotAuth, gotBody string
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		gotAuth = r.Header.Get("Authorization")
		var buf bytes.Buffer
		_, _ = buf.ReadFrom(r.Body)
		gotBody = buf.String()
		w.WriteHeader(http.StatusOK)
		_, _ = w.Write([]byte(`{"text":"x"}`))
	}))
	defer srv.Close()

	c := newClient(t, srv, "secret-key-123", "m")
	logBuf := logBuffer(t, c)

	audio := []byte("fake audio bytes")
	if _, _, err := c.TranscribeWithUsage(context.Background(), audio); err != nil {
		t.Fatalf("TranscribeWithUsage: %v", err)
	}
	if gotAuth != "Bearer secret-key-123" {
		t.Errorf("Authorization = %q, want the API key (the fake provider must see it)", gotAuth)
	}
	if !strings.Contains(gotBody, base64.StdEncoding.EncodeToString(audio)) {
		t.Errorf("the request body did not carry the base64 audio")
	}
	if strings.Contains(logBuf.String(), "secret-key-123") {
		t.Errorf("the API key reached the log: %s", logBuf.String())
	}
	if strings.Contains(logBuf.String(), base64.StdEncoding.EncodeToString(audio)) {
		t.Errorf("the audio payload reached the log: %s", logBuf.String())
	}
}

// A retry (a second call on the same client) emits one usage event per
// attempt, so retries are counted, not collapsed.
func TestRetriesEmitOneUsageEventPerAttempt(t *testing.T) {
	srv := httptest.NewServer(&fakeProvider{status: http.StatusInternalServerError, body: `{}`})
	defer srv.Close()

	c := newClient(t, srv, "key", "m")
	buf := logBuffer(t, c)

	for i := 0; i < 3; i++ {
		_, _, _ = c.TranscribeWithUsage(context.Background(), []byte("a"))
	}

	lines := strings.Split(strings.TrimSpace(buf.String()), "\n")
	if len(lines) != 3 {
		t.Fatalf("usage events = %d, want 3 (one per attempt): %s", len(lines), buf.String())
	}
	for i, line := range lines {
		var e map[string]any
		if err := json.Unmarshal([]byte(line), &e); err != nil {
			t.Fatalf("line %d: %v", i, err)
		}
		if e["outcome"] != "error" {
			t.Errorf("line %d: outcome = %v, want error", i, e["outcome"])
		}
	}
}
