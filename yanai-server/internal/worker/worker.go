// Package worker implements the in-process background job processor: a
// SELECT ... FOR UPDATE SKIP LOCKED claim loop over the jobs table, a
// handler registry keyed by job kind, and exponential-backoff retry
// bookkeeping. Isolated behind Run(ctx, ...) so it could later become its
// own binary or a Lambda handler without touching the HTTP layer.
package worker

import (
	"context"
	"encoding/json"
	"log/slog"
	"math"
	"os"
	"sync"
	"time"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"

	"yanai-server/internal/config"
	"yanai-server/internal/db"
)

// Job is the claimed row handed to a handler.
type Job struct {
	ID          int64
	TenantID    uuid.UUID // uuid.Nil for cross-tenant maintenance jobs
	Kind        string
	Payload     []byte
	Attempts    int16
	MaxAttempts int16
}

// HandlerFunc processes one claimed job inside its tenant transaction.
type HandlerFunc func(ctx context.Context, tx pgx.Tx, job Job) error

const pollInterval = 2 * time.Second

func Run(ctx context.Context, database *db.DB, cfg config.Config, logger *slog.Logger) {
	registry := defaultRegistry()
	workerName, _ := os.Hostname()
	if workerName == "" {
		workerName = "worker"
	}

	n := cfg.WorkerConcurrency
	if n < 1 {
		n = 1
	}

	var wg sync.WaitGroup
	for i := 0; i < n; i++ {
		wg.Add(1)
		go func(id int) {
			defer wg.Done()
			pollLoop(ctx, database, cfg.WorkerQueue, workerName, registry, logger)
		}(i)
	}

	wg.Wait()
}

func pollLoop(ctx context.Context, database *db.DB, queue, workerName string, registry map[string]HandlerFunc, logger *slog.Logger) {
	for {
		select {
		case <-ctx.Done():
			return
		default:
		}

		job, err := claim(ctx, database, queue, workerName)
		if err != nil {
			logger.Error("worker: claim", "error", err)
			sleep(ctx, pollInterval)
			continue
		}
		if job == nil {
			sleep(ctx, pollInterval)
			continue
		}

		dispatch(ctx, database, registry, *job, logger)
	}
}

func sleep(ctx context.Context, d time.Duration) {
	t := time.NewTimer(d)
	defer t.Stop()
	select {
	case <-ctx.Done():
	case <-t.C:
	}
}

func claim(ctx context.Context, database *db.DB, queue, workerName string) (*Job, error) {
	var j Job
	var tenantID *uuid.UUID
	err := database.Pool.QueryRow(ctx, `
		update jobs
		   set status = 'running', attempts = attempts + 1, attempted_at = now(), attempted_by = $1
		 where id = (
		   select id from jobs
		    where queue = $2 and status in ('available','retryable','scheduled') and run_after <= now()
		    order by priority, run_after, id
		    for update skip locked
		    limit 1
		 )
		returning id, tenant_id, kind, payload, attempts, max_attempts
	`, workerName, queue).Scan(&j.ID, &tenantID, &j.Kind, &j.Payload, &j.Attempts, &j.MaxAttempts)
	if err != nil {
		if err == pgx.ErrNoRows {
			return nil, nil
		}
		return nil, err
	}
	if tenantID != nil {
		j.TenantID = *tenantID
	}
	return &j, nil
}

func dispatch(ctx context.Context, database *db.DB, registry map[string]HandlerFunc, job Job, logger *slog.Logger) {
	handler, ok := registry[job.Kind]
	if !ok {
		recordFailure(ctx, database, job, "unknown job kind: "+job.Kind, logger)
		return
	}

	var handlerErr error
	if job.TenantID != uuid.Nil {
		tc := db.TenantCtx{TenantID: job.TenantID, RequestID: "job:" + job.Kind}
		handlerErr = database.WithTenantTx(ctx, tc, func(tx pgx.Tx) error {
			return handler(ctx, tx, job)
		})
	} else {
		handlerErr = database.WithSystemTx(ctx, func(tx pgx.Tx) error {
			return handler(ctx, tx, job)
		})
	}

	if handlerErr != nil {
		recordFailure(ctx, database, job, handlerErr.Error(), logger)
		return
	}
	recordSuccess(ctx, database, job, logger)
}

func recordSuccess(ctx context.Context, database *db.DB, job Job, logger *slog.Logger) {
	if _, err := database.Pool.Exec(ctx, `
		update jobs set status = 'completed', finalized_at = now() where id = $1
	`, job.ID); err != nil {
		logger.Error("worker: record success", "job_id", job.ID, "error", err)
	}
}

func recordFailure(ctx context.Context, database *db.DB, job Job, errMsg string, logger *slog.Logger) {
	logger.Error("worker: job failed", "job_id", job.ID, "kind", job.Kind, "error", errMsg)

	errRecord, _ := json.Marshal(map[string]any{"attempt": job.Attempts, "at": time.Now().UTC(), "error": truncate(errMsg, 2000)})
	backoffSeconds := math.Min(math.Pow(float64(job.Attempts), 4), 3600)

	if _, err := database.Pool.Exec(ctx, `
		update jobs set
		  status = case when attempts >= max_attempts then 'discarded' else 'retryable' end,
		  finalized_at = case when attempts >= max_attempts then now() end,
		  run_after = now() + make_interval(secs => $2),
		  errors = errors || jsonb_build_array($3::jsonb)
		where id = $1
	`, job.ID, backoffSeconds, errRecord); err != nil {
		logger.Error("worker: record failure", "job_id", job.ID, "error", err)
	}
}

func truncate(s string, n int) string {
	if len(s) <= n {
		return s
	}
	return s[:n]
}
