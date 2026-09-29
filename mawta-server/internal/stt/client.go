// Package stt sends recorded voice-note audio to OpenRouter's dedicated
// speech-to-text endpoint and returns the Spanish text it hears. One
// provider, one function — see the package SPEC for why there is no
// provider interface here.
//
// Every actual provider attempt also logs exactly one usage event (task,
// attempt, model, generation id, duration, outcome, and the cost the
// provider reported — never a price we invented). The event is emitted
// inside the call, before the caller's database write, so a later
// persistence failure cannot hide a billable call. It never carries the
// audio, the base64 payload, the transcript text, or the raw provider
// response or error body.
package stt

import (
	"bytes"
	"context"
	"encoding/base64"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"log/slog"
	"net/http"
	"time"

	"mawta-server/internal/logging"
)

const (
	defaultEndpoint = "https://openrouter.ai/api/v1/audio/transcriptions"
	// ProviderName is the provider identifier carried in the usage event.
	ProviderName = "openrouter"
)

// ErrPermanent wraps a transcription failure the worker should not retry: a
// missing API key, or a non-429 4xx from OpenRouter (bad/empty/unsupported
// audio, unknown model). Anything else — network errors, 429, 5xx — is
// returned unwrapped so the job's normal exponential backoff applies.
var ErrPermanent = errors.New("stt: permanent failure")

type Client struct {
	apiKey     string
	model      string
	endpoint   string
	httpClient *http.Client
	// logger is resolved lazily from slog.Default() when nil, so the client
	// picks up whatever logger cmd/api installed (slog.SetDefault) at the
	// time of the call rather than at construction. NewClient keeps its
	// two-argument signature — the worker registry builds the client before
	// the logger is handed to it — and tests can inject a buffer-backed
	// logger with SetLogger.
	logger *slog.Logger
}

// NewClient builds a client that logs one usage event per actual provider
// attempt. The events go to slog.Default() unless SetLogger installed a
// specific one; cmd/api sets the default to the configured JSON logger, so
// in production every usage event is a JSON line on stdout like every other
// application log entry.
func NewClient(apiKey, model string) *Client {
	if model == "" {
		model = "openai/whisper-large-v3"
	}
	return &Client{
		apiKey:     apiKey,
		model:      model,
		endpoint:   defaultEndpoint,
		httpClient: &http.Client{Timeout: 30 * time.Second},
	}
}

// SetLogger points the client at a specific logger. Used by tests; production
// relies on slog.Default() being the configured JSON logger.
func (c *Client) SetLogger(logger *slog.Logger) {
	c.logger = logger
}

// SetBaseURL points the client at a different transcription endpoint. Used by
// tests to stand a fake provider up on localhost; production never calls it,
// so the real endpoint stays the only one the process ever talks to.
func (c *Client) SetBaseURL(url string) {
	c.endpoint = url
}

// usageLogger returns the logger usage events go to.
func (c *Client) usageLogger() *slog.Logger {
	if c.logger != nil {
		return c.logger
	}
	return slog.Default()
}

type sttRequest struct {
	Model      string     `json:"model"`
	InputAudio inputAudio `json:"input_audio"`
	Language   string     `json:"language"`
}

type inputAudio struct {
	Data   string `json:"data"`
	Format string `json:"format"`
}

// UsageMetadata is what the provider reported about one transcription call.
// Every field is optional: the provider does not always report a cost, and a
// reported zero cost is a real zero, not a missing one. Nothing here is ever
// invented, priced locally, or inferred from a failure.
type UsageMetadata struct {
	// CostUSD is the provider-reported cost in USD. nil means the provider
	// did not report a cost.
	CostUSD *float64
	// GenerationID is the provider's generation id, when it returned one.
	GenerationID string
	// AudioSeconds is the provider-reported audio length in seconds.
	AudioSeconds *float64
	// Tokens is the provider-reported token count.
	Tokens *int64
}

// sttResponse is the subset of the provider response this package reads.
type sttResponse struct {
	Text string `json:"text"`
	// ID is the provider's generation id.
	ID string `json:"id"`
	// Usage mirrors the provider's usage object.
	Usage *sttUsage `json:"usage"`
}

type sttUsage struct {
	Cost         *float64 `json:"cost"`
	AudioSeconds *float64 `json:"audio_seconds"`
	Tokens       *int64   `json:"tokens"`
}

// Transcribe sends MP3 audio — the only format voice notes are ever stored
// in, see media.CanonicalMimeType — to OpenRouter and returns the Spanish
// text it hears.
//
// This is the two-value form the Transcriber interface in
// internal/worker/handlers is written against (and its existing test double
// implements exactly this signature, which is why it stays). The usage
// metadata is still collected and the usage event still logged on every
// provider attempt; callers that want the reported usage back call
// TranscribeWithUsage, which this delegates to.
func (c *Client) Transcribe(ctx context.Context, audioMP3 []byte) (string, error) {
	text, _, err := c.TranscribeWithUsage(ctx, audioMP3)
	return text, err
}

// TranscribeWithUsage is Transcribe and additionally returns what the
// provider reported about the call: cost (when reported), generation id,
// audio seconds and tokens. A reported zero cost comes back as a pointer to
// zero; a missing one as nil.
func (c *Client) TranscribeWithUsage(ctx context.Context, audioMP3 []byte) (string, UsageMetadata, error) {
	var usage UsageMetadata

	if c.apiKey == "" {
		// No provider call happens, so no usage event: there is nothing to
		// account. The permanent error is what the caller sees.
		return "", usage, fmt.Errorf("%w: TRANSCRIBE_OPENROUTER_API_KEY not configured", ErrPermanent)
	}

	reqBody := sttRequest{
		Model: c.model,
		InputAudio: inputAudio{
			Data:   base64.StdEncoding.EncodeToString(audioMP3),
			Format: "mp3",
		},
		Language: "es",
	}
	encoded, err := json.Marshal(reqBody)
	if err != nil {
		return "", usage, fmt.Errorf("stt: build request: %w", err)
	}

	req, err := http.NewRequestWithContext(ctx, http.MethodPost, c.endpoint, bytes.NewReader(encoded))
	if err != nil {
		return "", usage, fmt.Errorf("stt: build request: %w", err)
	}
	req.Header.Set("Authorization", "Bearer "+c.apiKey)
	req.Header.Set("Content-Type", "application/json")

	start := time.Now()
	resp, err := c.httpClient.Do(req)
	durationMs := time.Since(start).Milliseconds()
	if err != nil {
		c.logUsage(ctx, usage, durationMs, "error", "transient")
		return "", usage, fmt.Errorf("stt: request: %w", err) // network error: transient
	}
	defer resp.Body.Close()

	respBody, err := io.ReadAll(resp.Body)
	if err != nil {
		c.logUsage(ctx, usage, durationMs, "error", "transient")
		return "", usage, fmt.Errorf("stt: read response: %w", err)
	}

	// The provider's response body is never copied into an error (and so
	// never into a log or a jobs.errors row): it can contain anything, and
	// the status code plus the classification is what an operator needs.
	if resp.StatusCode == http.StatusTooManyRequests || resp.StatusCode >= 500 {
		err := fmt.Errorf("stt: transient error %d", resp.StatusCode)
		c.logUsage(ctx, usage, durationMs, "error", "transient")
		return "", usage, err
	}
	if resp.StatusCode != http.StatusOK {
		err := fmt.Errorf("%w: openrouter %d", ErrPermanent, resp.StatusCode)
		c.logUsage(ctx, usage, durationMs, "error", "permanent")
		return "", usage, err
	}

	var parsed sttResponse
	if err := json.Unmarshal(respBody, &parsed); err != nil {
		err = fmt.Errorf("stt: decode response: %w", err)
		c.logUsage(ctx, usage, durationMs, "error", "transient")
		return "", usage, err
	}

	usage = usageFromResponse(parsed)
	c.logUsage(ctx, usage, durationMs, "success", "")
	return parsed.Text, usage, nil
}

// usageFromResponse copies the provider-reported usage fields. A reported
// zero stays a pointer to zero; a missing field stays nil. Nothing is
// invented here.
func usageFromResponse(parsed sttResponse) UsageMetadata {
	var u UsageMetadata
	u.GenerationID = parsed.ID
	if parsed.Usage != nil {
		u.CostUSD = parsed.Usage.Cost
		u.AudioSeconds = parsed.Usage.AudioSeconds
		u.Tokens = parsed.Usage.Tokens
	}
	return u
}

// logUsage emits the one usage event for this provider attempt. The event
// carries only the classification, never the raw provider error body.
func (c *Client) logUsage(ctx context.Context, usage UsageMetadata, durationMs int64, outcome, errorClass string) {
	logger := c.usageLogger()
	if logger == nil {
		return
	}
	task, _ := logging.STTTaskFrom(ctx)
	event := logging.STTUsageEvent{
		TaskID:       task.TaskID,
		Attempt:      task.Attempt,
		Provider:     ProviderName,
		Model:        c.model,
		GenerationID: usage.GenerationID,
		DurationMs:   durationMs,
		Outcome:      outcome,
		ErrorClass:   errorClass,
		CostUSD:      usage.CostUSD,
		AudioSeconds: usage.AudioSeconds,
		Tokens:       usage.Tokens,
	}
	if event.CostUSD != nil {
		event.CostSource = logging.CostSourceProvider
	} else {
		event.CostSource = logging.CostSourceUnknown
	}
	logging.LogSTTUsage(logger, event)
}
