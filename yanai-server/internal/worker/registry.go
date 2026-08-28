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
	}
}
