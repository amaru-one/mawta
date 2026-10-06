package llm

import (
	"context"
	"encoding/json"
	"errors"
	"sync"
)

// FakeReply is one scripted answer of a Fake: a tool input, or an error.
type FakeReply struct {
	Input string
	Err   error
	Usage Usage
}

// Fake is a scripted Model for tests. It answers each call with the next
// reply and records every request, so a test can assert what the agent sent
// (and that it sent nothing when there was nothing to generate).
type Fake struct {
	mu      sync.Mutex
	Replies []FakeReply
	Calls   []Request
}

// ErrFakeExhausted is returned when a Fake runs out of replies.
var ErrFakeExhausted = errors.New("llm: fake has no more replies")

func (f *Fake) Name() string { return "fake-model" }

func (f *Fake) Generate(_ context.Context, req Request) (Response, error) {
	f.mu.Lock()
	defer f.mu.Unlock()
	f.Calls = append(f.Calls, req)
	if len(f.Replies) == 0 {
		return Response{}, ErrFakeExhausted
	}
	r := f.Replies[0]
	f.Replies = f.Replies[1:]
	resp := Response{Input: json.RawMessage(r.Input), Usage: r.Usage, MessageID: "fake", StopReason: "tool_use"}
	return resp, r.Err
}

// CallCount reports how many calls the fake received.
func (f *Fake) CallCount() int {
	f.mu.Lock()
	defer f.mu.Unlock()
	return len(f.Calls)
}
