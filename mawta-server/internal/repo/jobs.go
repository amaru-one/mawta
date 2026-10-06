package repo

import (
	"context"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"
)

// EnqueueJob inserts a job row, deduping against jobs_unique_key_idx when
// uniqueKey is non-empty. Runs inside the caller's tenant transaction so the
// enqueue is atomic with the write that triggered it.
func EnqueueJob(ctx context.Context, tx pgx.Tx, tenantID uuid.UUID, kind string, priority int16, payload []byte, uniqueKey string) error {
	var uk any
	if uniqueKey != "" {
		uk = uniqueKey
	}
	_, err := tx.Exec(ctx, `
		insert into jobs (tenant_id, kind, queue, priority, payload, unique_key)
		values ($1, $2, 'default', $3, $4, $5)
		on conflict (kind, unique_key) where unique_key is not null
		  and status in ('available','retryable','scheduled','running')
		do nothing
	`, tenantID, kind, priority, payload, uk)
	return err
}

// EnqueueJobWithAttempts is EnqueueJob with an explicit max_attempts, for
// jobs whose retries must stay few: a model call that keeps failing should
// fail its generation within seconds, not retry for hours (the default is
// 20).
func EnqueueJobWithAttempts(ctx context.Context, tx pgx.Tx, tenantID uuid.UUID, kind string, priority int16, payload []byte, uniqueKey string, maxAttempts int16) error {
	var uk any
	if uniqueKey != "" {
		uk = uniqueKey
	}
	_, err := tx.Exec(ctx, `
		insert into jobs (tenant_id, kind, queue, priority, payload, unique_key, max_attempts)
		values ($1, $2, 'default', $3, $4, $5, $6)
		on conflict (kind, unique_key) where unique_key is not null
		  and status in ('available','retryable','scheduled','running')
		do nothing
	`, tenantID, kind, priority, payload, uk, maxAttempts)
	return err
}
