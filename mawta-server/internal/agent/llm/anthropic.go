package llm

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"net/http"
	"strings"
	"time"

	"github.com/anthropics/anthropic-sdk-go"
	"github.com/anthropics/anthropic-sdk-go/option"
)

// Anthropic calls Claude through the Messages API with structured outputs.
type Anthropic struct {
	client anthropic.Client
	model  string
}

// NewAnthropic builds the client. An empty apiKey is allowed so the server
// boots without one; Generate then fails permanently and the HTTP layer
// answers agent_unavailable before ever enqueueing (see Configured).
func NewAnthropic(apiKey, model string, timeout time.Duration, opts ...option.RequestOption) *Anthropic {
	base := []option.RequestOption{
		option.WithAPIKey(apiKey),
		option.WithRequestTimeout(timeout),
		// One quick SDK retry absorbs a momentary 429/529; anything longer is
		// the job queue's backoff.
		option.WithMaxRetries(1),
	}
	a := &Anthropic{model: model}
	if apiKey != "" {
		a.client = anthropic.NewClient(append(base, opts...)...)
	}
	return a
}

// Configured reports whether an API key was provided.
func (a *Anthropic) Configured() bool { return a != nil && a.client.Options != nil }

func (a *Anthropic) Name() string { return a.model }

func (a *Anthropic) Generate(ctx context.Context, req Request) (Response, error) {
	if !a.Configured() {
		return Response{}, fmt.Errorf("%w: ANTHROPIC_API_KEY not configured", ErrPermanent)
	}

	system := make([]anthropic.TextBlockParam, 0, len(req.System))
	for _, b := range req.System {
		tb := anthropic.TextBlockParam{Text: b.Text}
		if b.Cache {
			tb.CacheControl = anthropic.NewCacheControlEphemeralParam()
		}
		system = append(system, tb)
	}
	// Structured outputs: the answer must be a JSON object matching the
	// tool's schema. (Forcing a tool call is not supported by every model —
	// claude-sonnet-5-5 rejects tool_choice "tool" — while structured outputs
	// guarantee the shape on all of them.)
	schema := strictSchema(map[string]any{
		"type":       "object",
		"properties": req.Tool.Properties,
		"required":   req.Tool.Required,
	})

	msg, err := a.client.Messages.New(ctx, anthropic.MessageNewParams{
		Model:        anthropic.Model(a.model),
		MaxTokens:    req.MaxTokens,
		System:       system,
		Messages:     []anthropic.MessageParam{anthropic.NewUserMessage(anthropic.NewTextBlock(req.Prompt))},
		OutputConfig: anthropic.OutputConfigParam{Format: anthropic.JSONOutputFormatParam{Schema: schema}},
	})
	if err != nil {
		return Response{}, classify(err)
	}

	resp := Response{
		MessageID:  msg.ID,
		StopReason: string(msg.StopReason),
		Usage: Usage{
			InputTokens:      msg.Usage.InputTokens,
			OutputTokens:     msg.Usage.OutputTokens,
			CacheReadTokens:  msg.Usage.CacheReadInputTokens,
			CacheWriteTokens: msg.Usage.CacheCreationInputTokens,
		},
	}
	if msg.StopReason == anthropic.StopReasonMaxTokens {
		return resp, fmt.Errorf("%w: answer cut off at max_tokens", ErrPermanent)
	}
	if msg.StopReason == anthropic.StopReasonRefusal {
		return resp, fmt.Errorf("%w: the model refused to answer", ErrPermanent)
	}
	var text strings.Builder
	for _, block := range msg.Content {
		if block.Type == "text" {
			text.WriteString(block.Text)
		}
	}
	answer := strings.TrimSpace(text.String())
	if answer == "" || !json.Valid([]byte(answer)) {
		return resp, fmt.Errorf("%w: the answer is not the requested JSON (stop_reason %s)", ErrPermanent, msg.StopReason)
	}
	resp.Input = json.RawMessage(answer)
	return resp, nil
}

// strictSchema closes every object of a JSON schema (additionalProperties:
// false), which structured outputs require, without changing the caller's
// map.
func strictSchema(node any) map[string]any {
	m, ok := node.(map[string]any)
	if !ok {
		return nil
	}
	out := make(map[string]any, len(m)+1)
	for k, v := range m {
		switch k {
		case "properties":
			props := map[string]any{}
			for name, p := range v.(map[string]any) {
				if sub := strictSchema(p); sub != nil {
					props[name] = sub
				} else {
					props[name] = p
				}
			}
			out[k] = props
		case "items":
			if sub := strictSchema(v); sub != nil {
				out[k] = sub
			} else {
				out[k] = v
			}
		default:
			out[k] = v
		}
	}
	if out["type"] == "object" {
		out["additionalProperties"] = false
	}
	return out
}

// classify sorts provider errors into transient (worth a retry) and
// permanent. The provider's error body is never included: it is not needed
// to decide, and the error text ends up in logs.
func classify(err error) error {
	var apiErr *anthropic.Error
	if errors.As(err, &apiErr) {
		switch {
		case apiErr.StatusCode == http.StatusTooManyRequests,
			apiErr.StatusCode == http.StatusRequestTimeout,
			apiErr.StatusCode >= 500:
			return fmt.Errorf("llm: provider status %d (transient)", apiErr.StatusCode)
		default:
			return fmt.Errorf("%w: provider status %d", ErrPermanent, apiErr.StatusCode)
		}
	}
	// Network failures and timeouts: transient. These errors come from the
	// HTTP client, not the provider, so they carry no response body.
	return fmt.Errorf("llm: request failed (transient): %w", err)
}
