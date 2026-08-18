package worker

import (
	"context"

	"github.com/jackc/pgx/v5"

	"yanai-server/internal/domain"
	"yanai-server/internal/worker/handlers"
)

// defaultRegistry adapts the handlers package's plain-argument functions
// (jobID, payload) to HandlerFunc. Handlers take plain arguments rather
// than a worker.Job so the handlers package never needs to import worker,
// which would otherwise cycle back through this registry.
func defaultRegistry() map[string]HandlerFunc {
	return map[string]HandlerFunc{
		domain.JobKindGradeRecompute: func(ctx context.Context, tx pgx.Tx, job Job) error {
			return handlers.GradeRecompute(ctx, tx, job.ID, job.Payload)
		},
		domain.JobKindRiskDetect: func(ctx context.Context, tx pgx.Tx, job Job) error {
			return handlers.RiskDetect(ctx, tx, job.Payload)
		},
		domain.JobKindNotificationSweep: func(ctx context.Context, tx pgx.Tx, job Job) error {
			return handlers.NotificationSweep(ctx, tx, job.Payload)
		},
		domain.JobKindNoteSummaryGenerate: func(ctx context.Context, tx pgx.Tx, job Job) error {
			return handlers.NoteSummaryGenerate(ctx, tx, job.ID, job.Payload)
		},
		domain.JobKindRetentionSweep: func(ctx context.Context, tx pgx.Tx, job Job) error {
			return handlers.RetentionSweep(ctx, tx, job.Payload)
		},
	}
}
