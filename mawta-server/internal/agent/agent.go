// Package agent is the shared base of Mawta's agents. Mawta runs several
// narrow agents — planning first, then sessions and descriptive conclusions —
// and none of them acts on its own: each generation is one bounded model
// call over data the server chose, answered by filling a fixed schema, and
// the server validates that answer and decides what is stored. What an
// agent proposes is saved as pending until the teacher accepts or edits it.
//
// This package owns what every agent repeats: the generation lifecycle in
// agent_generations, the model call outside any database transaction,
// retries, a one-time repair of an invalid answer, deadlines, usage and cost
// accounting. An agent only supplies what is its own: what context it reads
// (Prepare), what it asks (the Spec), and how it validates and stores the
// answer (Apply).
package agent

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"

	"github.com/jackc/pgx/v5"

	"mawta-server/internal/agent/llm"
	"mawta-server/internal/repo"
)

// Spec is the model call an agent wants to make.
type Spec struct {
	System    []llm.Block
	Prompt    string
	Tool      llm.Tool
	MaxTokens int64
}

// Prepared is what an agent's Prepare decided. Exactly one of Spec and
// Result is set: Result means there is nothing to generate (e.g. every
// capability already has a criterion) and the generation completes without
// calling the model. State is the agent's own context, handed back to Apply.
type Prepared struct {
	Spec   *Spec
	Result json.RawMessage
	State  any
}

// Agent is one of Mawta's agents.
type Agent interface {
	// Name is the agent_generations.agent value it serves, e.g. "planning".
	Name() string
	// PromptVersion identifies the instructions in use, recorded with each
	// generation so outputs can be traced to the prompt that produced them.
	PromptVersion() string
	// Prepare reads the context for a generation, inside a tenant
	// transaction.
	Prepare(ctx context.Context, tx pgx.Tx, gen repo.AgentGeneration) (Prepared, error)
	// Apply validates the model's answer against the current state of the
	// database and stores what passes, inside a tenant transaction. It
	// returns the generation's result. An answer that cannot be used at all
	// is reported with Invalid, which earns the model one repair attempt.
	Apply(ctx context.Context, tx pgx.Tx, gen repo.AgentGeneration, p Prepared, answer json.RawMessage) (json.RawMessage, error)
}

// InvalidAnswer reports a model answer the agent cannot use. Reason is fed
// back to the model in the repair attempt, so it is phrased for the model.
type InvalidAnswer struct{ Reason string }

func (e *InvalidAnswer) Error() string { return "invalid answer: " + e.Reason }

// Invalid builds an InvalidAnswer.
func Invalid(format string, args ...any) error {
	return &InvalidAnswer{Reason: fmt.Sprintf(format, args...)}
}

// IsInvalid reports whether err is an InvalidAnswer.
func IsInvalid(err error) bool {
	var ia *InvalidAnswer
	return errors.As(err, &ia)
}
