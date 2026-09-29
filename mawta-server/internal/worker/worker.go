// Package worker implements the in-process background job processor: a
// SELECT ... FOR UPDATE SKIP LOCKED claim loop over the jobs table, a
// handler registry keyed by job kind, and exponential-backoff retry
// bookkeeping. Isolated behind Run(ctx, ...) so it could later become its
// own binary or a Lambda handler without touching the HTTP layer.
//
// Every attempt emits a start event and exactly one terminal outcome event
// (success, retryable_failure, permanent_failure, or skipped), both carrying
// task_id — the queue job ID, the same integer the jobs table carries — plus
// the job kind, attempt number, max attempts, worker name, and the terminal
// duration. The outcome event is emitted only after the attempt's
// persistence has succeeded or failed, never before: a claim, transaction,
// or persistence failure stays visible as its own outcome.
package worker

import (
	"context"
	"encoding/json"
	"errors"
	"log/slog"
	"math"
	"os"
	"sync"
	"time"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"

	"mawta-server/internal/config"
	"mawta-server/internal/db"
	"mawta-server/internal/logging"
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
	// The registry builds the STT client itself (registry.go), and that
	// client resolves its usage-event logger from slog.Default() — which
	// cmd/api has already pointed at the configured JSON logger — so no
	// logger needs to be threaded through the registry here.
	registry := defaultRegistry(cfg)
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

		dispatch(ctx, database, registry, *job, workerName, logger)
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

// dispatch runs one claimed job to a terminal outcome. It emits the start
// event, runs the handler inside the job's transaction, persists the
// outcome, and only then emits the terminal outcome event — so the event
// never claims a completion the database has not recorded.
func dispatch(ctx context.Context, database *db.DB, registry map[string]HandlerFunc, job Job, workerName string, logger *slog.Logger) {
	start := time.Now()
	logging.LogJobStart(logger, logging.JobStartEvent{
		TaskID:      job.ID,
		JobID:       job.ID,
		Kind:        job.Kind,
		Attempt:     job.Attempts,
		MaxAttempts: job.MaxAttempts,
		WorkerName:  workerName,
	})

	emit := func(outcome, reason, errText string) {
		logging.LogJobOutcome(logger, logging.JobOutcomeEvent{
			TaskID:      job.ID,
			JobID:       job.ID,
			Kind:        job.Kind,
			Attempt:     job.Attempts,
			MaxAttempts: job.MaxAttempts,
			WorkerName:  workerName,
			Outcome:     outcome,
			Reason:      reason,
			DurationMs:  time.Since(start).Milliseconds(),
			Error:       errText,
		})
	}
	// fail persists a failed attempt, then reports it with the outcome the
	// queue will actually apply: retried while attempts remain, discarded
	// (a permanent failure) on the last one or when it cannot be recorded.
	fail := func(reason string, cause error) {
		outcome := logging.OutcomeRetryableFailure
		if job.Attempts >= job.MaxAttempts {
			outcome = logging.OutcomePermanentFailure
		}
		errText := logging.SanitizeErrorCause(cause)
		if err := persistFailure(ctx, database, job, cause.Error(), logger); err != nil {
			// Unrecorded, the job stays running and is never claimed again.
			outcome, reason, errText = logging.OutcomePermanentFailure, "persistence_error", logging.SanitizeErrorCause(err)
		}
		emit(outcome, reason, errText)
	}

	handler, ok := registry[job.Kind]
	if !ok {
		fail("unknown_kind", errors.New("unknown job kind: "+job.Kind))
		return
	}

	// The task identity rides the context so the STT client can log usage
	// against the right task_id/attempt without a signature change, and the
	// handler can report an attempt that finished without doing its work.
	taskCtx, report := logging.WithOutcomeReport(logging.WithSTTTask(ctx, logging.STTTask{TaskID: job.ID, Attempt: job.Attempts}))

	var handlerErr error
	if job.TenantID != uuid.Nil {
		tc := db.TenantCtx{TenantID: job.TenantID, RequestID: "job:" + job.Kind}
		handlerErr = database.WithTenantTx(taskCtx, tc, func(tx pgx.Tx) error {
			return handler(taskCtx, tx, job)
		})
	} else {
		handlerErr = database.WithSystemTx(taskCtx, func(tx pgx.Tx) error {
			return handler(taskCtx, tx, job)
		})
	}
	if handlerErr != nil {
		fail("handler_error", handlerErr)
		return
	}

	// The handler's transaction committed; the job is only complete once its
	// status is recorded. A job whose completion cannot be recorded stays
	// running and is never claimed again, so it is reported as a permanent
	// failure, never as a success.
	if err := persistSuccess(ctx, database, job); err != nil {
		logger.Error("worker: record success", "task_id", job.ID, "job_id", job.ID, "error", logging.SanitizeErrorCause(err))
		emit(logging.OutcomePermanentFailure, "persistence_error", logging.SanitizeErrorCause(err))
		return
	}
	if report.Outcome != "" {
		emit(report.Outcome, report.Reason, "")
		return
	}
	emit(logging.OutcomeSuccess, "", "")
}

// persistSuccess writes the completed status. It is called before the
// outcome event so the event never precedes the persistence it describes.
func persistSuccess(ctx context.Context, database *db.DB, job Job) error {
	_, err := database.Pool.Exec(ctx, `
		update jobs set status = 'completed', finalized_at = now() where id = $1
	`, job.ID)
	return err
}

// persistFailure writes the retry/discard bookkeeping. It is called before
// the outcome event so the event never precedes the persistence it describes.
func persistFailure(ctx context.Context, database *db.DB, job Job, errMsg string, logger *slog.Logger) error {
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
		logger.Error("worker: record failure", "task_id", job.ID, "job_id", job.ID, "error", logging.SanitizeErrorCause(err))
		return err
	}
	return nil
}

func truncate(s string, n int) string {
	if len(s) <= n {
		return s
	}
	return s[:n]
}
