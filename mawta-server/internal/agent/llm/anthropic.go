package llm

import (
	"context"
	"errors"
	"fmt"
	"net/http"
	"time"

	"github.com/anthropics/anthropic-sdk-go"
	"github.com/anthropics/anthropic-sdk-go/option"
)

// Anthropic calls Claude through the Messages API with a forced tool call.
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
	tool := anthropic.ToolParam{
		Name:        req.Tool.Name,
		Description: anthropic.String(req.Tool.Description),
		InputSchema: anthropic.ToolInputSchemaParam{
			Properties: req.Tool.Properties,
			Required:   req.Tool.Required,
		},
	}

	msg, err := a.client.Messages.New(ctx, anthropic.MessageNewParams{
		Model:      anthropic.Model(a.model),
		MaxTokens:  req.MaxTokens,
		System:     system,
		Messages:   []anthropic.MessageParam{anthropic.NewUserMessage(anthropic.NewTextBlock(req.Prompt))},
		Tools:      []anthropic.ToolUnionParam{{OfTool: &tool}},
		ToolChoice: anthropic.ToolChoiceParamOfTool(req.Tool.Name),
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
	for _, block := range msg.Content {
		if block.Type == "tool_use" && block.Name == req.Tool.Name {
			resp.Input = block.Input
			return resp, nil
		}
	}
	return resp, fmt.Errorf("%w: the model did not call %s (stop_reason %s)", ErrPermanent, req.Tool.Name, msg.StopReason)
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
