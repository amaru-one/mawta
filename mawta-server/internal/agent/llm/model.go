// Package llm is how Mawta's agents call a language model. It exposes one
// narrow operation — a single request that must answer by filling one tool's
// JSON schema — so every agent gets structured output it can validate before
// anything reaches the database. Agents depend on the Model interface; the
// Anthropic implementation lives in anthropic.go and a scripted fake for
// tests in fake.go.
package llm

import (
	"context"
	"encoding/json"
	"errors"
)

// ErrPermanent marks a failure that retrying will not fix: no API key, a
// request the provider rejects (4xx other than rate limits), or an answer
// that does not fill the tool. Anything else (rate limits, overload, 5xx,
// network, timeouts) is transient and worth retrying.
var ErrPermanent = errors.New("llm: permanent failure")

// Block is one part of the system instructions. Cache marks a stable block
// (instructions, curriculum) the provider may cache across calls, which makes
// repeated generations for the same class cheaper and faster.
type Block struct {
	Text  string
	Cache bool
}

// Tool is the only way the model may answer: it must call this tool, and the
// tool's input is the structured answer.
type Tool struct {
	Name        string
	Description string
	// Properties and Required are the JSON schema of the tool's input object.
	Properties map[string]any
	Required   []string
}

// Request is one model call.
type Request struct {
	System    []Block
	Prompt    string
	Tool      Tool
	MaxTokens int64
}

// Usage is what one call consumed, as the provider reports it.
type Usage struct {
	InputTokens      int64
	OutputTokens     int64
	CacheReadTokens  int64
	CacheWriteTokens int64
}

// Response is the tool input the model produced.
type Response struct {
	Input      json.RawMessage
	Usage      Usage
	MessageID  string
	StopReason string
}

// Model is a language model an agent can call.
type Model interface {
	// Generate runs one request. On error the returned Response may still
	// carry the usage of a call that was billed (e.g. an answer that did not
	// fill the tool), so callers record it either way.
	Generate(ctx context.Context, req Request) (Response, error)
	// Name is the model identifier recorded with each generation.
	Name() string
}

// Prices are a model's prices in US dollars per million tokens. They come
// from configuration: the server does not guess them, and with no prices a
// generation records its tokens and a zero, unknown cost.
type Prices struct {
	InputPerMTok      float64
	OutputPerMTok     float64
	CacheReadPerMTok  float64
	CacheWritePerMTok float64
}

// Known reports whether any price is configured.
func (p Prices) Known() bool {
	return p.InputPerMTok > 0 || p.OutputPerMTok > 0
}

// Cost estimates what a call cost.
func (p Prices) Cost(u Usage) float64 {
	const m = 1_000_000.0
	return float64(u.InputTokens)*p.InputPerMTok/m +
		float64(u.OutputTokens)*p.OutputPerMTok/m +
		float64(u.CacheReadTokens)*p.CacheReadPerMTok/m +
		float64(u.CacheWriteTokens)*p.CacheWritePerMTok/m
}
