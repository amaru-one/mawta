// Package logging configures structured JSON logging for mawta-server.
// It provides a slog.Logger that writes one JSON object per line to stdout,
// includes a stable service identifier, and respects the LOG_LEVEL environment
// variable.
//
// It also owns the observability vocabulary shared by the HTTP and worker
// layers: the HTTP request/response body capture policy (allowlist, size
// bound, capture statuses), the worker job outcome events, and the STT
// transcription usage events. Those live here rather than in httpapi/worker
// so the security rules about what may reach stdout are stated once, in one
// place, next to the logger itself.
package logging

import (
	"context"
	"encoding/json"
	"io"
	"log/slog"
	"os"
	"strings"
	"time"
)

const ServiceName = "mawta-server"

// MaxBodyBytes is the hard bound on a captured HTTP request or response body.
// A body larger than this is never captured — never truncated — and the
// completion event reports too_large instead. 16 KiB is far above every
// allowlisted field this package permits and far below anything that could
// matter for debugging a JSON API.
const MaxBodyBytes = 16 * 1024

// CaptureStatus explains what the request/response fields of an HTTP
// completion event hold. The six values are the whole vocabulary; anything
// else must not be invented at a call site.
type CaptureStatus string

const (
	// CaptureCaptured: the body was captured and is present, sanitized, in
	// the request/response field.
	CaptureCaptured CaptureStatus = "captured"
	// CaptureEmpty: the body was genuinely empty (GET with no body, a 204
	// response). The field is JSON null. Distinct from a captured JSON null.
	CaptureEmpty CaptureStatus = "empty"
	// CaptureDisabled: body capture is off (the production default). The
	// field is null and the metadata is still emitted.
	CaptureDisabled CaptureStatus = "disabled"
	// CaptureOmitted: the route or a field inside it is not on the allowlist,
	// or the body is not JSON the policy will log. The field is null.
	CaptureOmitted CaptureStatus = "omitted"
	// CaptureInvalidJSON: the body claimed to be JSON but did not parse. The
	// raw bytes are never logged.
	CaptureInvalidJSON CaptureStatus = "invalid_json"
	// CaptureTooLarge: the body exceeded MaxBodyBytes. The field is null; the
	// exchange itself is untouched.
	CaptureTooLarge CaptureStatus = "too_large"
)

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

// EnvRequestBodyCapture is the environment variable behind body capture.
// It is read here — not only in internal/config — because the HTTP
// middleware is handed just a logger (the router wires
// requestLogger(a.logger)), so the flag reaches it through this function
// rather than through Config. internal/config reads the same name for
// Config.RequestBodyCapture; the two cannot disagree because they share this
// one implementation.
const EnvRequestBodyCapture = "REQUEST_BODY_CAPTURE"

// RequestBodyCaptureFromEnv reports whether HTTP body capture is enabled.
// Off unless explicitly set: bodies can carry school content about minors.
func RequestBodyCaptureFromEnv() bool {
	v := strings.TrimSpace(os.Getenv(EnvRequestBodyCapture))
	if v == "" {
		return false
	}
	switch strings.ToLower(v) {
	case "1", "t", "true", "yes", "y", "on":
		return true
	default:
		return false
	}
}

// ---------------------------------------------------------------------------
// HTTP body capture
// ---------------------------------------------------------------------------

// CapturePolicy is the whole security rule for HTTP body capture: whether it
// is on at all, the size bound, and the route-and-field allowlist that
// decides what may be logged. It is immutable once built.
type CapturePolicy struct {
	// Enabled is false in production unless REQUEST_BODY_CAPTURE is set.
	Enabled bool
	// MaxBytes bounds a captured body. Larger bodies are omitted (too_large),
	// never truncated.
	MaxBytes int
	// Allowlist maps a Chi route pattern to the top-level JSON object fields
	// that may be logged for that route. A route absent from the map is
	// never captured. An empty field set for a present route means the body
	// is captured only if it is an empty object.
	Allowlist map[string][]string
}

// DefaultAllowlist is the documented route-and-field allowlist.
//
// The rule it encodes: only fields that are structural, non-free-text, and
// carry no student data. Concretely excluded — by omission here, and by the
// denylist in sanitizeValue — are:
//
//   - credentials: username, password, token, secret, api_key, key,
//     authorization (any nesting, any array element)
//   - cookies and session material (the middleware never reads headers at all)
//   - audio and transcripts: the voice-note upload route is not allowlisted,
//     and audio/transcript fields are denied everywhere
//   - student records and grades: student_id, raw_value, max_score, level,
//     score, grade, value — a mark or a student identifier is never logged
//   - free-text school content: title, description, body, note, name, text,
//     username, code — the words a teacher or a student wrote
//
// What remains is deliberately narrow: identifiers of the *thing being acted
// on* (capability_id), structural flags (kind, value_scale,
// status), and numbers that describe the request
// rather than a person (minutes_late).
//
// Every entry is a Chi route pattern, never a raw path: the middleware looks
// up the pattern, so an unmatched URL never matches an entry and its
// parameters are never logged.
var DefaultAllowlist = map[string][]string{
	// Attendance: status and lateness only. The note field is free text and
	// is not allowlisted.
	"/api/v1/sessions/{sessionID}/attendance/{studentID}":      {"status", "minutes_late"},
	"/api/v1/sessions/{sessionID}/attendance/mark-all-present": {},

	// Session lifecycle: no body to speak of, listed so an unexpected body is
	// omitted rather than falling through to "route not allowlisted".
	"/api/v1/sessions/{sessionID}/start": {},

	// Evidence authoring: structural fields only. Title is free text;
	// max_score, student_id and criterion_ids are student data.
	"/api/v1/classes/{classID}/assessments": {"kind", "value_scale", "due_at"},

	// Soft deletes: no body.
	"/api/v1/assessments/{assessmentID}/delete": {},
	"/api/v1/criteria/{criterionID}/delete":     {},

	// Criterion authoring: capability_id only. Description and code are the
	// teacher's own words.
	"/api/v1/classes/{classID}/competencies/{competencyID}/criteria": {"capability_id"},

	// Capability authoring: nothing safe to log (code and name are both
	// school content), listed to make the omission explicit.
	"/api/v1/competencies/{competencyID}/capabilities": {},

	// Notifications: no body.
	"/api/v1/notifications/{notificationID}/read": {},
	"/api/v1/notifications/read-all":              {},

	// Voice note lifecycle: no body (the upload route, which carries audio,
	// is deliberately absent from this map).
	"/api/v1/voice-notes/{voiceNoteID}/save":    {},
	"/api/v1/voice-notes/{voiceNoteID}/discard": {},

	// Auth: never. Username and password are credentials; logout has no body.
	// Both routes are absent so even a future body on them is omitted.
}

// NewCapturePolicy builds the policy. enabled is Config.RequestBodyCapture /
// the logger's baked-in flag; the allowlist and the size bound are fixed here
// so a caller cannot widen them by construction.
func NewCapturePolicy(enabled bool) CapturePolicy {
	return CapturePolicy{Enabled: enabled, MaxBytes: MaxBodyBytes, Allowlist: DefaultAllowlist}
}

// CapturedBody is the sanitized value plus the status explaining it.
type CapturedBody struct {
	// Value is the sanitized JSON value to log, or nil for every status
	// other than captured. It is a decoded value (map/slice/number/bool/nil),
	// never a string holding JSON, so it is never double-encoded.
	Value any
	// Status is one of the CaptureStatus values.
	Status CaptureStatus
}

// CaptureRequestBody sanitizes a request body for the route pattern. It is
// given the Chi route pattern, never the raw path, so unmatched URLs cannot
// reach the allowlist. Headers, cookies, the authorization header and the
// query string are never arguments to it and therefore never logged.
func (p CapturePolicy) CaptureRequestBody(routePattern, contentType string, body []byte) CapturedBody {
	if !p.Enabled {
		return CapturedBody{Status: CaptureDisabled}
	}
	if !isJSONContentType(contentType) {
		// Multipart uploads (audio) and anything non-JSON are omitted.
		return CapturedBody{Status: CaptureOmitted}
	}
	return p.captureBody(routePattern, body)
}

// CaptureResponseBody sanitizes a response body for the route pattern. The
// same allowlist governs both directions: a response field is exactly as
// sensitive as the request field of the same name.
func (p CapturePolicy) CaptureResponseBody(routePattern, contentType string, body []byte) CapturedBody {
	if !p.Enabled {
		return CapturedBody{Status: CaptureDisabled}
	}
	if !isJSONContentType(contentType) {
		// Binary and streamed responses (audio, files) are omitted, never
		// sniffed.
		return CapturedBody{Status: CaptureOmitted}
	}
	return p.captureBody(routePattern, body)
}

func (p CapturePolicy) captureBody(routePattern string, body []byte) CapturedBody {
	if len(body) == 0 {
		return CapturedBody{Status: CaptureEmpty}
	}
	if p.MaxBytes > 0 && len(body) > p.MaxBytes {
		return CapturedBody{Status: CaptureTooLarge}
	}
	fields, ok := p.Allowlist[routePattern]
	if !ok {
		// A route not on the allowlist — including every unmatched path,
		// which never has a pattern — is omitted outright.
		return CapturedBody{Status: CaptureOmitted}
	}
	var decoded any
	if err := json.Unmarshal(body, &decoded); err != nil {
		// Never log the raw bytes of malformed JSON.
		return CapturedBody{Status: CaptureInvalidJSON}
	}
	obj, ok := decoded.(map[string]any)
	if !ok {
		// A bare JSON scalar/array is not a body this policy describes.
		return CapturedBody{Status: CaptureOmitted}
	}
	out := make(map[string]any, len(fields))
	for _, f := range fields {
		v, present := obj[f]
		if !present {
			continue
		}
		// The denylist wins over the allowlist at the top level too, so a
		// mistaken allowlist entry cannot open a denied field.
		if deniedFields[f] {
			out[f] = nil
			continue
		}
		out[f] = sanitizeValue(v)
	}
	return CapturedBody{Value: out, Status: CaptureCaptured}
}

func isJSONContentType(contentType string) bool {
	if contentType == "" {
		return false
	}
	media := contentType
	if i := strings.IndexByte(media, ';'); i >= 0 {
		media = media[:i]
	}
	return strings.TrimSpace(strings.ToLower(media)) == "application/json"
}

// deniedFields are never logged, at any depth, in any array element, under
// any route. The allowlist already keeps most of them out; this is the second
// lock, so a future allowlist entry cannot accidentally open one.
var deniedFields = map[string]bool{
	// credentials and secrets
	"password": true, "passwd": true, "secret": true, "token": true,
	"api_key": true, "apikey": true, "key": true, "authorization": true,
	"auth": true, "cookie": true, "cookies": true, "session": true,
	// audio and transcripts
	"audio": true, "input_audio": true, "data": true, "transcript": true,
	"transcription": true,
	// student records and grades
	"student_id": true, "student": true, "grade": true, "grades": true,
	"score": true, "scores": true, "raw_value": true, "max_score": true,
	"level": true, "value": true, "note": true, "notes": true,
	// free-text school content
	"title": true, "description": true, "body": true, "text": true,
	"name": true, "username": true, "code": true, "q": true,
}

// sanitizeValue reduces a decoded JSON value to what may be logged. Nested
// objects and arrays are walked; a denied key anywhere in them drops that
// subtree to nil rather than logging a partial object that implies more
// than it says.
func sanitizeValue(v any) any {
	switch t := v.(type) {
	case map[string]any:
		out := make(map[string]any, len(t))
		for k, vv := range t {
			if deniedFields[k] {
				out[k] = nil
				continue
			}
			out[k] = sanitizeValue(vv)
		}
		return out
	case []any:
		out := make([]any, len(t))
		for i, vv := range t {
			out[i] = sanitizeValue(vv)
		}
		return out
	case string:
		// A string that is not a denied field is still free text someone
		// typed. Allowlist entries only ever name non-free-text fields, but
		// a long string is a smell regardless: drop it rather than ship it.
		if len(t) > 200 {
			return nil
		}
		return t
	default:
		// numbers, booleans, null
		return v
	}
}

// ---------------------------------------------------------------------------
// Error correlation
// ---------------------------------------------------------------------------

// SanitizeErrorCause renders an internal error for the log under a
// request_id. It logs the error's own text — the cause a developer needs —
// but never a raw body, a header value, or a query string, because none of
// those are arguments to it. A nil error renders as the empty string so a
// call site can pass an error it did not check.
func SanitizeErrorCause(err error) string {
	if err == nil {
		return ""
	}
	msg := err.Error()
	if len(msg) > 500 {
		msg = msg[:500]
	}
	return msg
}

// ---------------------------------------------------------------------------
// Worker job events
// ---------------------------------------------------------------------------

// Worker job outcomes. The four values are the whole vocabulary.
const (
	OutcomeSuccess          = "success"
	OutcomeRetryableFailure = "retryable_failure"
	OutcomePermanentFailure = "permanent_failure"
	OutcomeSkipped          = "skipped"
)

// JobStartEvent is one worker attempt beginning. Emitted after the claim
// succeeds and before the handler runs, so a job that dies mid-handler is
// visible as a start with no terminal event.
type JobStartEvent struct {
	TaskID      int64
	JobID       int64
	Kind        string
	Attempt     int16
	MaxAttempts int16
	WorkerName  string
}

// LogJobStart emits the start event. task_id is the queue job ID — the same
// integer the jobs table carries — and job_id repeats it for the field name
// the existing events used, so a dashboard keyed on either finds both.
func LogJobStart(logger *slog.Logger, e JobStartEvent) {
	if logger == nil {
		return
	}
	logger.Info("worker: job started",
		"event", "worker.job_started",
		"task_id", e.TaskID,
		"job_id", e.JobID,
		"kind", e.Kind,
		"attempt", e.Attempt,
		"max_attempts", e.MaxAttempts,
		"worker", e.WorkerName,
	)
}

// JobOutcomeEvent is the terminal event for one worker attempt. Exactly one
// is emitted per attempt, after the attempt's persistence has succeeded or
// failed — never before.
type JobOutcomeEvent struct {
	TaskID      int64
	JobID       int64
	Kind        string
	Attempt     int16
	MaxAttempts int16
	WorkerName  string
	// Outcome is one of the Outcome* constants.
	Outcome string
	// Reason is a safe, short classification (e.g. "handler_error",
	// "unknown_kind", "persistence_error"). Never a payload, never a
	// transcript, never a raw provider body.
	Reason string
	// DurationMs is the terminal duration of the attempt.
	DurationMs int64
	// Error is the sanitized cause for failure outcomes; empty otherwise.
	Error string
}

// LogJobOutcome emits the terminal outcome event. A failed job is logged at
// error level, a skipped one at info: a skip is a normal, decided outcome,
// not something to page anyone about.
func LogJobOutcome(logger *slog.Logger, e JobOutcomeEvent) {
	if logger == nil {
		return
	}
	attrs := []any{
		"event", "worker.job_outcome",
		"task_id", e.TaskID,
		"job_id", e.JobID,
		"kind", e.Kind,
		"attempt", e.Attempt,
		"max_attempts", e.MaxAttempts,
		"worker", e.WorkerName,
		"outcome", e.Outcome,
		"duration_ms", e.DurationMs,
	}
	if e.Reason != "" {
		attrs = append(attrs, "reason", e.Reason)
	}
	if e.Error != "" {
		attrs = append(attrs, "error", e.Error)
	}
	switch e.Outcome {
	case OutcomeSuccess, OutcomeSkipped:
		logger.Info("worker: job "+e.Outcome, attrs...)
	default:
		logger.Error("worker: job "+e.Outcome, attrs...)
	}
}

// ---------------------------------------------------------------------------
// STT usage events
// ---------------------------------------------------------------------------

// Cost sources for the transcription usage event.
const (
	CostSourceProvider = "provider"
	CostSourceUnknown  = "unknown"
)

// STTUsageEvent is one actual provider attempt. Exactly one usage event is
// emitted per provider call, including calls whose later database write
// fails, so the accounting never under-reports what was spent.
type STTUsageEvent struct {
	// TaskID is the queue job ID the attempt belongs to.
	TaskID int64
	// Attempt is the job attempt number (1-based, the jobs.attempts value).
	Attempt int16
	// Provider is the provider name, e.g. "openrouter".
	Provider string
	// Model is the requested model string.
	Model string
	// GenerationID is the provider's generation id, when it returned one.
	GenerationID string
	// DurationMs is the wall time of the provider call.
	DurationMs int64
	// Outcome is "success" or "error".
	Outcome string
	// ErrorClass is a safe classification ("permanent", "transient", "" on
	// success). Never a raw provider error body.
	ErrorClass string
	// CostUSD is the provider-reported cost. nil means the provider did not
	// report one; a reported zero stays numeric zero. Never invented.
	CostUSD *float64
	// CostSource is CostSourceProvider when CostUSD came from the provider,
	// CostSourceUnknown when it is nil.
	CostSource string
	// AudioSeconds is the provider-reported audio length, when present.
	AudioSeconds *float64
	// Tokens is the provider-reported token count, when present.
	Tokens *int64
}

// AgentUsageEvent is one language-model call made by a Mawta agent. Like
// STTUsageEvent it is emitted per call, retries included, and never carries
// the prompt, the answer, or any school content — only identifiers, sizes
// and cost.
type AgentUsageEvent struct {
	GenerationID     string
	Agent            string
	Kind             string
	Model            string
	Attempt          int16
	DurationMs       int64
	Outcome          string // "success" or "error"
	ErrorClass       string // "permanent", "transient", "invalid_output" or ""
	InputTokens      int64
	OutputTokens     int64
	CacheReadTokens  int64
	CacheWriteTokens int64
	// CostUSD is the estimate from the configured prices; nil when no prices
	// are configured. Never invented.
	CostUSD *float64
}

// LogAgentUsage emits the usage event of one agent model call.
func LogAgentUsage(logger *slog.Logger, e AgentUsageEvent) {
	if logger == nil {
		return
	}
	attrs := []any{
		"event", "agent.usage",
		"generation_id", e.GenerationID,
		"agent", e.Agent,
		"kind", e.Kind,
		"model", e.Model,
		"attempt", e.Attempt,
		"duration_ms", e.DurationMs,
		"outcome", e.Outcome,
		"input_tokens", e.InputTokens,
		"output_tokens", e.OutputTokens,
		"cache_read_tokens", e.CacheReadTokens,
		"cache_write_tokens", e.CacheWriteTokens,
	}
	if e.ErrorClass != "" {
		attrs = append(attrs, "error_class", e.ErrorClass)
	}
	if e.CostUSD != nil {
		attrs = append(attrs, "cost_usd", *e.CostUSD, "cost_source", "configured_prices")
	} else {
		attrs = append(attrs, "cost_usd", nil, "cost_source", CostSourceUnknown)
	}
	if e.Outcome == "success" {
		logger.Info("agent usage", attrs...)
		return
	}
	logger.Warn("agent usage", attrs...)
}

// LogSTTUsage emits the one usage event for a provider attempt. It never
// receives the audio, the base64 payload, the transcript text, or the raw
// provider response, so none of them can reach stdout through it.
func LogSTTUsage(logger *slog.Logger, e STTUsageEvent) {
	if logger == nil {
		return
	}
	attrs := []any{
		"event", "stt.usage",
		"task_id", e.TaskID,
		"attempt", e.Attempt,
		"provider", e.Provider,
		"model", e.Model,
		"duration_ms", e.DurationMs,
		"outcome", e.Outcome,
	}
	if e.GenerationID != "" {
		attrs = append(attrs, "generation_id", e.GenerationID)
	}
	if e.ErrorClass != "" {
		attrs = append(attrs, "error_class", e.ErrorClass)
	}
	if e.CostUSD != nil {
		attrs = append(attrs, "cost_usd", *e.CostUSD, "cost_source", CostSourceProvider)
	} else {
		attrs = append(attrs, "cost_usd", nil, "cost_source", CostSourceUnknown)
	}
	if e.AudioSeconds != nil {
		attrs = append(attrs, "audio_seconds", *e.AudioSeconds)
	}
	if e.Tokens != nil {
		attrs = append(attrs, "tokens", *e.Tokens)
	}
	if e.Outcome == "success" {
		logger.Info("stt: transcription usage", attrs...)
	} else {
		logger.Warn("stt: transcription usage", attrs...)
	}
}

// sttTaskKey is the context key for the transcription task identity.
type sttTaskKey struct{}

// STTTask identifies the job a provider call belongs to.
type STTTask struct {
	TaskID  int64
	Attempt int16
}

// WithSTTTask returns a context carrying the transcription task identity.
// The worker puts it there before calling the handler, so the STT client can
// log usage against the right task_id/attempt without any other signature
// change.
func WithSTTTask(ctx context.Context, task STTTask) context.Context {
	return context.WithValue(ctx, sttTaskKey{}, task)
}

// STTTaskFrom returns the task identity in ctx, if any.
func STTTaskFrom(ctx context.Context) (STTTask, bool) {
	task, ok := ctx.Value(sttTaskKey{}).(STTTask)
	return task, ok
}

type outcomeReportKey struct{}

// OutcomeReport is what a handler says its attempt amounted to when it
// returns nil. A job can finish (its transaction commits) while the work it
// was for failed or had nothing to do — for example a transcription the
// provider refused permanently, recorded as failed on the voice note. The
// worker reads the report after the job's completion is persisted, so such an
// attempt is never logged as a success.
type OutcomeReport struct {
	Outcome string
	Reason  string
}

// WithOutcomeReport returns a context a handler can report into, and the
// report the worker reads back.
func WithOutcomeReport(ctx context.Context) (context.Context, *OutcomeReport) {
	report := &OutcomeReport{}
	return context.WithValue(ctx, outcomeReportKey{}, report), report
}

// ReportOutcome records a non-success outcome (OutcomeSkipped or
// OutcomePermanentFailure) and a safe reason for the current job attempt. It
// does nothing outside a worker job.
func ReportOutcome(ctx context.Context, outcome, reason string) {
	if report, ok := ctx.Value(outcomeReportKey{}).(*OutcomeReport); ok {
		report.Outcome, report.Reason = outcome, reason
	}
}

// FormatDurationMs is a small helper for callers that need the same duration
// rendering the events use.
func FormatDurationMs(d time.Duration) int64 { return d.Milliseconds() }
