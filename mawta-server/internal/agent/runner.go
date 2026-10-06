package agent

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"log/slog"
	"time"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"

	"mawta-server/internal/agent/llm"
	"mawta-server/internal/db"
	"mawta-server/internal/domain"
	"mawta-server/internal/logging"
	"mawta-server/internal/repo"
)

// Messages a teacher reads when a generation fails. They never carry a
// technical cause: that goes to agent_generations.error_detail.
const (
	MsgRetryLater    = "Mawta no pudo generar ahora. Intenta de nuevo en un momento o escríbelo a mano."
	MsgInvalidAnswer = "Mawta no logró una propuesta válida esta vez. Intenta de nuevo o escríbelo a mano."
	MsgUnavailable   = "Mawta no está disponible en este momento. Puedes escribirlo a mano."
	msgGone          = "Lo que pediste generar ya no existe. Vuelve a cargar la pantalla."
)

// JobKind is the job that runs a generation (jobs.kind).
const JobKind = domain.JobKindAgentGenerate

// MaxAttempts bounds a generation's retries: transient model failures are
// retried a couple of times with the queue's backoff, then the generation
// fails and the teacher can write by hand.
const MaxAttempts = 3

// JobPayload is what the queued job carries: only the generation id, never
// any content (jobs has no RLS).
type JobPayload struct {
	GenerationID uuid.UUID `json:"generation_id"`
}

// Runner runs generations for the registered agents.
type Runner struct {
	DB     *db.DB
	Model  llm.Model
	Prices llm.Prices
	Logger *slog.Logger
	agents map[string]Agent
}

// NewRunner builds a runner over a model and its agents.
func NewRunner(database *db.DB, model llm.Model, prices llm.Prices, logger *slog.Logger, agents ...Agent) *Runner {
	r := &Runner{DB: database, Model: model, Prices: prices, Logger: logger, agents: map[string]Agent{}}
	for _, a := range agents {
		r.agents[a.Name()] = a
	}
	return r
}

// Outcome tells the worker how an attempt ended when it did not fail
// transiently: Skipped (nothing to do) or Failed (recorded as failed, do not
// retry). The empty Outcome is a completed generation.
type Outcome string

const (
	OutcomeCompleted Outcome = ""
	OutcomeSkipped   Outcome = "skipped"
	OutcomeFailed    Outcome = "failed"
)

// Run executes one attempt of a generation job. It never holds a database
// transaction open while the model is called: it prepares in one
// transaction, calls the model, then applies the answer in another, against
// fresh data. A returned error means a transient failure the queue should
// retry; anything final is recorded on the generation and reported through
// the Outcome.
func (r *Runner) Run(ctx context.Context, tenantID uuid.UUID, payload []byte, attempt, maxAttempts int16) (Outcome, error) {
	var p JobPayload
	if err := json.Unmarshal(payload, &p); err != nil || p.GenerationID == uuid.Nil {
		return OutcomeSkipped, nil
	}
	tc := db.TenantCtx{TenantID: tenantID, RequestID: "job:" + JobKind}
	lastAttempt := attempt >= maxAttempts

	// 1. Claim the generation and read its context.
	var gen repo.AgentGeneration
	var prep Prepared
	var ag Agent
	var outcome Outcome = OutcomeCompleted
	err := r.DB.WithTenantTx(ctx, tc, func(tx pgx.Tx) error {
		g, ok, err := repo.StartGeneration(ctx, tx, p.GenerationID)
		if err != nil {
			if errors.Is(err, pgx.ErrNoRows) {
				outcome = OutcomeSkipped
				return nil
			}
			return err
		}
		if !ok {
			outcome = OutcomeSkipped
			return nil
		}
		gen = g
		a, found := r.agents[g.Agent]
		if !found {
			outcome = OutcomeFailed
			return r.fail(ctx, tx, g, MsgUnavailable, "no agent registered for "+g.Agent, repo.Usage{})
		}
		ag = a
		prep, err = a.Prepare(ctx, tx, g)
		if err != nil {
			if msg, final := finalMessage(err); final {
				outcome = OutcomeFailed
				return r.fail(ctx, tx, g, msg, err.Error(), repo.Usage{})
			}
			return err
		}
		if prep.Result != nil {
			return r.complete(ctx, tx, g, prep.Result, repo.Usage{PromptVersion: a.PromptVersion()})
		}
		return nil
	})
	if err != nil {
		return OutcomeCompleted, err
	}
	if outcome != OutcomeCompleted || prep.Result != nil {
		return outcome, nil
	}

	// 2. Call the model (with one repair round for an unusable answer), then
	// 3. apply the answer in a fresh transaction.
	usage := repo.Usage{Model: r.Model.Name(), PromptVersion: ag.PromptVersion()}
	spec := *prep.Spec
	for round := 0; round < 2; round++ {
		resp, callErr := r.call(ctx, gen, attempt, spec)
		usage = addUsage(usage, r.usage(resp.Usage))
		if callErr != nil {
			if errors.Is(callErr, llm.ErrPermanent) {
				return OutcomeFailed, r.failTx(ctx, tc, gen, MsgInvalidAnswer, callErr.Error(), usage)
			}
			if lastAttempt {
				return OutcomeFailed, r.failTx(ctx, tc, gen, MsgRetryLater, callErr.Error(), usage)
			}
			if err := r.DB.WithTenantTx(ctx, tc, func(tx pgx.Tx) error {
				return repo.RecordGenerationUsage(ctx, tx, gen.ID, usage)
			}); err != nil {
				return OutcomeCompleted, err
			}
			return OutcomeCompleted, callErr
		}

		var applyErr error
		var final bool
		err := r.DB.WithTenantTx(ctx, tc, func(tx pgx.Tx) error {
			current, err := repo.GetGeneration(ctx, tx, gen.ID)
			if err != nil {
				return err
			}
			if current.Status != repo.GenerationRunning || current.Expired(time.Now()) {
				// Expired or finished elsewhere: never store a late answer.
				final = true
				if current.Status == repo.GenerationRunning {
					return r.fail(ctx, tx, current, repo.ExpiredGenerationMessage, "answer arrived after the deadline", usage)
				}
				return nil
			}
			result, err := ag.Apply(ctx, tx, current, prep, resp.Input)
			if err != nil {
				applyErr = err
				return err // roll back anything Apply wrote
			}
			final = true
			return r.complete(ctx, tx, current, result, usage)
		})
		if final && err == nil {
			return OutcomeCompleted, nil
		}
		if applyErr == nil {
			return OutcomeCompleted, err
		}
		if IsInvalid(applyErr) && round == 0 {
			spec = repairSpec(spec, resp.Input, applyErr)
			continue
		}
		if IsInvalid(applyErr) {
			return OutcomeFailed, r.failTx(ctx, tc, gen, MsgInvalidAnswer, applyErr.Error(), usage)
		}
		if msg, isFinal := finalMessage(applyErr); isFinal {
			return OutcomeFailed, r.failTx(ctx, tc, gen, msg, applyErr.Error(), usage)
		}
		return OutcomeCompleted, applyErr
	}
	return OutcomeFailed, r.failTx(ctx, tc, gen, MsgInvalidAnswer, "no usable answer after repair", usage)
}

// call makes one model call and logs its usage.
func (r *Runner) call(ctx context.Context, gen repo.AgentGeneration, attempt int16, spec Spec) (llm.Response, error) {
	start := time.Now()
	resp, err := r.Model.Generate(ctx, llm.Request{
		System:    spec.System,
		Prompt:    spec.Prompt,
		Tool:      spec.Tool,
		MaxTokens: spec.MaxTokens,
	})
	ev := logging.AgentUsageEvent{
		GenerationID:     gen.ID.String(),
		Agent:            gen.Agent,
		Kind:             gen.Kind,
		Model:            r.Model.Name(),
		Attempt:          attempt,
		DurationMs:       time.Since(start).Milliseconds(),
		Outcome:          "success",
		InputTokens:      resp.Usage.InputTokens,
		OutputTokens:     resp.Usage.OutputTokens,
		CacheReadTokens:  resp.Usage.CacheReadTokens,
		CacheWriteTokens: resp.Usage.CacheWriteTokens,
	}
	if err != nil {
		ev.Outcome, ev.ErrorClass = "error", "transient"
		if errors.Is(err, llm.ErrPermanent) {
			ev.ErrorClass = "permanent"
		}
	}
	if r.Prices.Known() {
		cost := r.Prices.Cost(resp.Usage)
		ev.CostUSD = &cost
	}
	logging.LogAgentUsage(r.Logger, ev)
	return resp, err
}

func (r *Runner) usage(u llm.Usage) repo.Usage {
	out := repo.Usage{
		InputTokens:      u.InputTokens,
		OutputTokens:     u.OutputTokens,
		CacheReadTokens:  u.CacheReadTokens,
		CacheWriteTokens: u.CacheWriteTokens,
	}
	if r.Prices.Known() {
		out.CostUSD = r.Prices.Cost(u)
	}
	return out
}

func addUsage(a, b repo.Usage) repo.Usage {
	a.InputTokens += b.InputTokens
	a.OutputTokens += b.OutputTokens
	a.CacheReadTokens += b.CacheReadTokens
	a.CacheWriteTokens += b.CacheWriteTokens
	a.CostUSD += b.CostUSD
	return a
}

// repairSpec asks the model once more, telling it what was wrong with its
// previous answer.
func repairSpec(spec Spec, previous json.RawMessage, why error) Spec {
	spec.Prompt = fmt.Sprintf("%s\n\n<respuesta_anterior>\n%s\n</respuesta_anterior>\n\n"+
		"Tu respuesta anterior no se pudo usar: %s\n"+
		"Vuelve a responder usando la herramienta, corrigiendo eso y usando solo los ids entregados.",
		spec.Prompt, string(previous), why.(*InvalidAnswer).Reason)
	return spec
}

// finalMessage maps an error that retrying will not fix to the teacher's
// message. Domain errors (the experience was deleted, a competency is no
// longer in it) are final; database and network errors are not.
func finalMessage(err error) (string, bool) {
	if errors.Is(err, pgx.ErrNoRows) {
		return msgGone, true
	}
	var appErr *db.AppError
	if errors.As(err, &appErr) {
		if appErr.Status == 404 {
			return msgGone, true
		}
		if appErr.Status < 500 {
			return appErr.Message, true
		}
	}
	return "", false
}

func (r *Runner) complete(ctx context.Context, tx pgx.Tx, g repo.AgentGeneration, result json.RawMessage, u repo.Usage) error {
	if err := repo.CompleteGeneration(ctx, tx, g.ID, result, u); err != nil {
		return err
	}
	return logGenerationEvent(ctx, tx, "agent.generation.completed", g)
}

func (r *Runner) fail(ctx context.Context, tx pgx.Tx, g repo.AgentGeneration, msg, detail string, u repo.Usage) error {
	if err := repo.FailGeneration(ctx, tx, g.ID, msg, detail, u); err != nil {
		return err
	}
	return logGenerationEvent(ctx, tx, "agent.generation.failed", g)
}

// failTx records a failure in its own transaction. Its error, if any, is
// what the worker sees.
func (r *Runner) failTx(ctx context.Context, tc db.TenantCtx, g repo.AgentGeneration, msg, detail string, u repo.Usage) error {
	return r.DB.WithTenantTx(ctx, tc, func(tx pgx.Tx) error {
		current, err := repo.GetGeneration(ctx, tx, g.ID)
		if err != nil {
			return err
		}
		if current.Status == repo.GenerationCompleted || current.Status == repo.GenerationFailed {
			return nil
		}
		return r.fail(ctx, tx, current, msg, detail, u)
	})
}

func logGenerationEvent(ctx context.Context, tx pgx.Tx, action string, g repo.AgentGeneration) error {
	payload, _ := json.Marshal(map[string]string{"agent": g.Agent, "kind": g.Kind})
	id := g.ID
	classID := g.ClassID
	return repo.LogEvent(ctx, tx, action, "agent_generation", &id, payload, nil, &classID, nil)
}
