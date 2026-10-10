package worker

import (
	"context"
	"log/slog"

	"github.com/jackc/pgx/v5"

	"mawta-server/internal/agent"
	"mawta-server/internal/agent/llm"
	"mawta-server/internal/agent/planning"
	"mawta-server/internal/agent/redaction"
	"mawta-server/internal/config"
	"mawta-server/internal/db"
	"mawta-server/internal/domain"
	"mawta-server/internal/logging"
	"mawta-server/internal/stt"
	"mawta-server/internal/worker/handlers"
)

// defaultRegistry adapts the handlers package's plain-argument functions
// (jobID, payload) to HandlerFunc. Handlers take plain arguments rather
// than a worker.Job so the handlers package never needs to import worker,
// which would otherwise cycle back through this registry.
//
// voice_note.transcribe is the first kind whose handler needs a dependency
// beyond ctx/tx/payload (an STT service) — it's built once here, not per
// job, and closed over by the plain-argument function handlers.VoiceNoteTranscribe
// returns.
//
// agent.generate runs Mawta's agents. It manages its own transactions
// (OwnTx): a model call can take a minute and must not hold a transaction
// open while it waits.
func defaultRegistry(cfg config.Config, database *db.DB, logger *slog.Logger) Registry {
	sttClient := stt.NewClient(cfg.TranscribeAPIKey, cfg.TranscribeModel)
	// A saved transcript queues its name sweep, but only when the agents can
	// run: without a key every sweep would fail, and the note simply stays
	// pending until one is configured (the conclusions endpoint queues
	// pending notes again).
	var afterTranscript []handlers.AfterTranscript
	if cfg.AnthropicAPIKey != "" {
		afterTranscript = append(afterTranscript, redaction.QueueAfterTranscript)
	}
	transcribe := handlers.VoiceNoteTranscribe(sttClient, afterTranscript...)

	model := llm.NewAnthropic(cfg.AnthropicAPIKey, cfg.PlanningAgentModel, cfg.AgentTimeout)
	prices := llm.Prices{
		InputPerMTok:      cfg.AgentPriceInputPerMTok,
		OutputPerMTok:     cfg.AgentPriceOutputPerMTok,
		CacheReadPerMTok:  cfg.AgentPriceCacheReadPerMTok,
		CacheWritePerMTok: cfg.AgentPriceCacheWritePerMTok,
	}
	runner := agent.NewRunner(database, model, prices, logger, planning.New())
	runner.Bind(redaction.New(),
		llm.NewAnthropic(cfg.AnthropicAPIKey, cfg.RedactionAgentModel, cfg.AgentTimeout),
		llm.Prices(cfg.RedactionAgentPrices))

	return Registry{
		InTx: map[string]HandlerFunc{
			domain.JobKindVoiceNoteTranscribe: func(ctx context.Context, tx pgx.Tx, job Job) error {
				return transcribe(ctx, tx, job.ID, job.Payload)
			},
		},
		OwnTx: map[string]OwnTxHandlerFunc{
			domain.JobKindAgentGenerate: AgentGenerate(runner),
		},
	}
}

// AgentGenerate adapts an agent runner to a job handler: a transient failure
// is returned so the queue retries it; a skipped or failed generation is
// final and reported as such, so the job is not retried.
func AgentGenerate(runner *agent.Runner) OwnTxHandlerFunc {
	return func(ctx context.Context, job Job) error {
		outcome, err := runner.Run(ctx, job.TenantID, job.Payload, job.Attempts, job.MaxAttempts)
		if err != nil {
			return err
		}
		switch outcome {
		case agent.OutcomeSkipped:
			logging.ReportOutcome(ctx, logging.OutcomeSkipped, "generation_not_runnable")
		case agent.OutcomeFailed:
			logging.ReportOutcome(ctx, logging.OutcomePermanentFailure, "generation_failed")
		}
		return nil
	}
}
