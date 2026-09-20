package worker_test

import (
	"context"
	"os"
	"testing"

	"github.com/jackc/pgx/v5"

	"yanai-server/internal/dbtest"
	"yanai-server/internal/repo"
)

func TestMain(m *testing.M) { os.Exit(dbtest.Main(m)) }

// These tests exercise the jobs table directly rather than through worker.Run,
// which loops forever and builds its own registry internally. What is asserted
// here is the queue's behaviour — claim eligibility, dedup, and what an
// abandoned job does — because that is where the surprises live.

const claim = `
	update jobs
	   set status = 'running', attempts = attempts + 1, attempted_at = now(), attempted_by = $1
	 where id = (
	   select id from jobs
	    where queue = 'default' and status in ('available','retryable','scheduled') and run_after <= now()
	    order by priority, run_after, id
	    for update skip locked
	    limit 1
	 )
	returning id, kind`

// enqueue puts a job on the queue through the real repo function, in its own
// committed transaction, and returns a cleanup that removes it.
func enqueue(t *testing.T, env *dbtest.Env, kind, uniqueKey string) {
	t.Helper()
	ctx := context.Background()

	tx, err := env.App.Pool.Begin(ctx)
	if err != nil {
		t.Fatalf("begin: %v", err)
	}
	if err := repo.EnqueueJob(ctx, tx, env.Fx.TenantA, kind, 2, []byte(`{}`), uniqueKey); err != nil {
		tx.Rollback(ctx) //nolint:errcheck
		t.Fatalf("EnqueueJob: %v", err)
	}
	if err := tx.Commit(ctx); err != nil {
		t.Fatalf("commit: %v", err)
	}

	t.Cleanup(func() {
		if _, err := env.App.Pool.Exec(ctx, `delete from jobs where unique_key = $1`, uniqueKey); err != nil {
			t.Errorf("cleanup jobs: %v", err)
		}
	})
}

func statusOf(t *testing.T, env *dbtest.Env, uniqueKey string) (status string, attempts int) {
	t.Helper()
	if err := env.App.Pool.QueryRow(context.Background(),
		`select status, attempts from jobs where unique_key = $1`, uniqueKey).Scan(&status, &attempts); err != nil {
		t.Fatalf("read job: %v", err)
	}
	return
}

func TestClaimTakesAnAvailableJobAndMarksItRunning(t *testing.T) {
	env := dbtest.Setup(t)
	ctx := context.Background()
	const key = "grade.recompute:claim-probe"
	enqueue(t, env, "grade.recompute", key)

	var id int64
	var kind string
	if err := env.App.Pool.QueryRow(ctx, claim, "test-worker").Scan(&id, &kind); err != nil {
		t.Fatalf("claim: %v", err)
	}
	if kind != "grade.recompute" {
		t.Errorf("claimed kind = %q", kind)
	}

	status, attempts := statusOf(t, env, key)
	if status != "running" {
		t.Errorf("status = %q, want running", status)
	}
	if attempts != 1 {
		t.Errorf("attempts = %d, want 1", attempts)
	}
}

// A running job is invisible to the claim query. That is what stops two
// workers doing the same work — and, below, what makes an abandoned job
// permanent.
func TestARunningJobIsNotClaimedAgain(t *testing.T) {
	env := dbtest.Setup(t)
	ctx := context.Background()
	const key = "grade.recompute:double-claim-probe"
	enqueue(t, env, "grade.recompute", key)

	var id int64
	var kind string
	if err := env.App.Pool.QueryRow(ctx, claim, "worker-1").Scan(&id, &kind); err != nil {
		t.Fatalf("first claim: %v", err)
	}

	err := env.App.Pool.QueryRow(ctx, claim, "worker-2").Scan(&id, &kind)
	if err != pgx.ErrNoRows {
		t.Errorf("second claim returned %v, want no rows — a running job must not be claimable", err)
	}
}

// Documented behaviour (internal/worker/SPEC.md: "No lease reaper"). Asserted
// so the day someone adds recovery, this test fails and has to be updated
// deliberately rather than the behaviour changing unnoticed.
func TestAnAbandonedRunningJobIsNeverRecovered(t *testing.T) {
	env := dbtest.Setup(t)
	ctx := context.Background()
	const key = "grade.recompute:abandoned-probe"
	enqueue(t, env, "grade.recompute", key)

	var id int64
	var kind string
	if err := env.App.Pool.QueryRow(ctx, claim, "worker-that-dies").Scan(&id, &kind); err != nil {
		t.Fatalf("claim: %v", err)
	}
	// The worker process dies here. Nothing ever moves the row off 'running'.

	if err := env.App.Pool.QueryRow(ctx, claim, "worker-that-lives").Scan(&id, &kind); err != pgx.ErrNoRows {
		t.Errorf("an abandoned job was re-claimed (%v); if a reaper was added, update this test and the SPEC together", err)
	}

	status, _ := statusOf(t, env, key)
	if status != "running" {
		t.Errorf("status = %q, want running — the row is stranded, by design", status)
	}
}

// The consequence of the two facts above, and worth stating outright because
// the documented symptom understates it.
//
// jobs_unique_key_idx includes 'running' in its predicate, so while a job is
// running, EnqueueJob for the same key is a silent no-op. Combined with the
// absent reaper, a worker that dies mid-job leaves that dedup key poisoned
// permanently: every future grade.recompute for that student/class/term is
// dropped, and the student's internal grade silently stops updating.
//
// SPEC.md says "a job whose worker dies stays running; diagnose via
// attempted_by/attempted_at", which reads like one lost job. It is not.
func TestAnAbandonedJobPermanentlyBlocksItsDedupKey(t *testing.T) {
	env := dbtest.Setup(t)
	ctx := context.Background()
	const key = "grade.recompute:poisoned-key-probe"
	enqueue(t, env, "grade.recompute", key)

	var id int64
	var kind string
	if err := env.App.Pool.QueryRow(ctx, claim, "worker-that-dies").Scan(&id, &kind); err != nil {
		t.Fatalf("claim: %v", err)
	}

	// A teacher writes three more scores. Each tries to enqueue a recompute.
	for i := 0; i < 3; i++ {
		tx, err := env.App.Pool.Begin(ctx)
		if err != nil {
			t.Fatalf("begin: %v", err)
		}
		if err := repo.EnqueueJob(ctx, tx, env.Fx.TenantA, "grade.recompute", 2, []byte(`{}`), key); err != nil {
			tx.Rollback(ctx) //nolint:errcheck
			t.Fatalf("EnqueueJob: %v", err)
		}
		if err := tx.Commit(ctx); err != nil {
			t.Fatalf("commit: %v", err)
		}
	}

	var n int
	if err := env.App.Pool.QueryRow(ctx, `select count(*) from jobs where unique_key = $1`, key).Scan(&n); err != nil {
		t.Fatalf("count: %v", err)
	}
	if n != 1 {
		t.Fatalf("jobs for the key = %d, want 1", n)
	}

	// Nothing is claimable, and nothing new was enqueued: the work is lost and
	// will stay lost.
	if err := env.App.Pool.QueryRow(ctx, claim, "later-worker").Scan(&id, &kind); err != pgx.ErrNoRows {
		t.Errorf("claim returned %v; this test encodes the CURRENT behaviour — if recovery was added, update it and the SPEC together", err)
	}
}

// A finished job frees its key, so the next score write enqueues normally.
// This is the contrast that makes the case above a defect rather than a rule.
func TestACompletedJobReleasesItsDedupKey(t *testing.T) {
	env := dbtest.Setup(t)
	ctx := context.Background()
	const key = "grade.recompute:released-key-probe"
	enqueue(t, env, "grade.recompute", key)

	if _, err := env.App.Pool.Exec(ctx,
		`update jobs set status = 'completed', finalized_at = now() where unique_key = $1`, key); err != nil {
		t.Fatalf("finalize: %v", err)
	}

	tx, err := env.App.Pool.Begin(ctx)
	if err != nil {
		t.Fatalf("begin: %v", err)
	}
	if err := repo.EnqueueJob(ctx, tx, env.Fx.TenantA, "grade.recompute", 2, []byte(`{}`), key); err != nil {
		tx.Rollback(ctx) //nolint:errcheck
		t.Fatalf("EnqueueJob: %v", err)
	}
	if err := tx.Commit(ctx); err != nil {
		t.Fatalf("commit: %v", err)
	}

	var n int
	if err := env.App.Pool.QueryRow(ctx, `select count(*) from jobs where unique_key = $1`, key).Scan(&n); err != nil {
		t.Fatalf("count: %v", err)
	}
	if n != 2 {
		t.Errorf("jobs for the key = %d, want 2 — a completed job must not keep blocking its key", n)
	}
}

// The worker only ever polls 'default'. A job on another queue is never
// claimed, which is why repo.EnqueueJob hardcodes it.
func TestAJobOnAnotherQueueIsNeverClaimed(t *testing.T) {
	env := dbtest.Setup(t)
	ctx := context.Background()
	const key = "grade.recompute:other-queue-probe"

	if _, err := env.App.Pool.Exec(ctx,
		`insert into jobs (tenant_id, kind, queue, priority, payload, unique_key)
		 values ($1, 'grade.recompute', 'somewhere-else', 2, '{}', $2)`,
		env.Fx.TenantA, key); err != nil {
		t.Fatalf("insert: %v", err)
	}
	t.Cleanup(func() {
		env.App.Pool.Exec(ctx, `delete from jobs where unique_key = $1`, key) //nolint:errcheck
	})

	var id int64
	var kind string
	if err := env.App.Pool.QueryRow(ctx, claim, "test-worker").Scan(&id, &kind); err != pgx.ErrNoRows {
		t.Errorf("claim returned %v, want no rows for a job outside the default queue", err)
	}
}

// jobs sits outside RLS on purpose: cross-tenant maintenance work has no
// tenant. Worth asserting, because a nullable tenant_id on a table full of
// student-related work looks like an oversight until you know it is not.
func TestJobsTenantIDIsNullable(t *testing.T) {
	env := dbtest.Setup(t)
	ctx := context.Background()

	var id int64
	if err := env.App.Pool.QueryRow(ctx,
		`insert into jobs (kind, queue, priority, payload) values ('maintenance.probe', 'default', 4, '{}') returning id`).
		Scan(&id); err != nil {
		t.Fatalf("insert a nil-tenant job: %v", err)
	}
	t.Cleanup(func() {
		env.App.Pool.Exec(ctx, `delete from jobs where id = $1`, id) //nolint:errcheck
	})

	var tenantID *string
	if err := env.App.Pool.QueryRow(ctx, `select tenant_id::text from jobs where id = $1`, id).Scan(&tenantID); err != nil {
		t.Fatalf("read: %v", err)
	}
	if tenantID != nil {
		t.Errorf("tenant_id = %v, want null", *tenantID)
	}
}
