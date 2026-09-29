package worker

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"log/slog"
	"strings"
	"testing"

	"github.com/jackc/pgx/v5"

	"mawta-server/internal/dbtest"
	"mawta-server/internal/logging"
	"mawta-server/internal/repo"
)

// These tests run the real claim and dispatch against the test database and
// assert on the terminal outcome event dispatch emits, not on log lines the
// test writes itself.

const dispatchKind = "test.dispatch"

// runOne enqueues one job, claims it, dispatches it with handler, and returns
// the single outcome event and the job's final status.
func runOne(t *testing.T, env *dbtest.Env, key string, maxAttempts int, ctx context.Context, handler HandlerFunc) (map[string]any, string) {
	t.Helper()
	setup := context.Background()
	tx, err := env.App.Pool.Begin(setup)
	if err != nil {
		t.Fatalf("begin: %v", err)
	}
	if err := repo.EnqueueJob(setup, tx, env.Fx.TenantA, dispatchKind, 2, []byte(`{}`), key); err != nil {
		tx.Rollback(setup) //nolint:errcheck
		t.Fatalf("EnqueueJob: %v", err)
	}
	if err := tx.Commit(setup); err != nil {
		t.Fatalf("commit: %v", err)
	}
	t.Cleanup(func() {
		if _, err := env.Admin.Pool.Exec(setup, `delete from jobs where unique_key = $1`, key); err != nil {
			t.Errorf("cleanup jobs: %v", err)
		}
	})
	if _, err := env.Admin.Pool.Exec(setup, `update jobs set max_attempts = $2 where unique_key = $1`, key, maxAttempts); err != nil {
		t.Fatalf("set max_attempts: %v", err)
	}

	job, err := claim(setup, env.App, "default", "test-worker")
	if err != nil || job == nil {
		t.Fatalf("claim: %v %v", job, err)
	}
	var want int64
	if err := env.Admin.Pool.QueryRow(setup, `select id from jobs where unique_key = $1`, key).Scan(&want); err != nil || job.ID != want {
		t.Fatalf("claimed job %d, want %d (%v)", job.ID, want, err)
	}

	var buf bytes.Buffer
	logger := slog.New(slog.NewJSONHandler(&buf, nil))
	dispatch(ctx, env.App, map[string]HandlerFunc{dispatchKind: handler}, *job, "test-worker", logger)

	var outcomes []map[string]any
	for _, line := range strings.Split(strings.TrimSpace(buf.String()), "\n") {
		var entry map[string]any
		if json.Unmarshal([]byte(line), &entry) == nil && entry["event"] == "worker.job_outcome" {
			outcomes = append(outcomes, entry)
		}
	}
	if len(outcomes) != 1 {
		t.Fatalf("want exactly one outcome event, got %d:\n%s", len(outcomes), buf.String())
	}
	var status string
	if err := env.Admin.Pool.QueryRow(setup, `select status from jobs where unique_key = $1`, key).Scan(&status); err != nil {
		t.Fatalf("read status: %v", err)
	}
	return outcomes[0], status
}

func TestDispatchReportsSkippedWorkAsSkipped(t *testing.T) {
	env := dbtest.Setup(t)
	event, status := runOne(t, env, "dispatch:skipped", 3, context.Background(), func(ctx context.Context, tx pgx.Tx, job Job) error {
		logging.ReportOutcome(ctx, logging.OutcomeSkipped, "nothing_to_do")
		return nil
	})
	if event["outcome"] != logging.OutcomeSkipped || event["reason"] != "nothing_to_do" {
		t.Errorf("outcome = %v reason = %v, want skipped/nothing_to_do", event["outcome"], event["reason"])
	}
	if event["task_id"] != event["job_id"] || event["task_id"] == nil {
		t.Errorf("task_id %v must equal job_id %v", event["task_id"], event["job_id"])
	}
	if status != "completed" {
		t.Errorf("status = %q, want completed", status)
	}
}

// A handler that records a failure on its domain row returns nil so the
// record commits; the attempt must still not be logged as a success.
func TestDispatchNeverReportsAFailedTranscriptionAsSuccess(t *testing.T) {
	env := dbtest.Setup(t)
	event, status := runOne(t, env, "dispatch:failed-work", 3, context.Background(), func(ctx context.Context, tx pgx.Tx, job Job) error {
		logging.ReportOutcome(ctx, logging.OutcomePermanentFailure, "transcription_failed")
		return nil
	})
	if event["outcome"] != logging.OutcomePermanentFailure || event["reason"] != "transcription_failed" {
		t.Errorf("outcome = %v reason = %v, want permanent_failure/transcription_failed", event["outcome"], event["reason"])
	}
	if status != "completed" {
		t.Errorf("status = %q, want completed (the failure is recorded, the job is done)", status)
	}
}

func TestDispatchClassifiesHandlerErrorsByTheQueuesFate(t *testing.T) {
	env := dbtest.Setup(t)
	failing := func(ctx context.Context, tx pgx.Tx, job Job) error { return errors.New("boom") }

	event, status := runOne(t, env, "dispatch:retryable", 3, context.Background(), failing)
	if event["outcome"] != logging.OutcomeRetryableFailure || status != "retryable" {
		t.Errorf("attempt 1 of 3: outcome = %v status = %q, want retryable_failure/retryable", event["outcome"], status)
	}

	event, status = runOne(t, env, "dispatch:last-attempt", 1, context.Background(), failing)
	if event["outcome"] != logging.OutcomePermanentFailure || status != "discarded" {
		t.Errorf("last attempt: outcome = %v status = %q, want permanent_failure/discarded", event["outcome"], status)
	}
}

// When the outcome cannot be persisted, the job stays running and is never
// claimed again: the event must say so, not claim a completion.
func TestDispatchNeverLogsSuccessWhenPersistenceFails(t *testing.T) {
	env := dbtest.Setup(t)
	ctx, cancel := context.WithCancel(context.Background())
	event, status := runOne(t, env, "dispatch:unpersisted", 3, ctx, func(ctx context.Context, tx pgx.Tx, job Job) error {
		cancel() // the handler "succeeds", but nothing after it can be recorded
		return nil
	})
	if event["outcome"] == logging.OutcomeSuccess {
		t.Fatalf("an unrecorded attempt was logged as a success: %v", event)
	}
	if event["outcome"] != logging.OutcomePermanentFailure || event["reason"] != "persistence_error" {
		t.Errorf("outcome = %v reason = %v, want permanent_failure/persistence_error", event["outcome"], event["reason"])
	}
	if status != "running" {
		t.Errorf("status = %q, want running (nothing could be recorded)", status)
	}
}
