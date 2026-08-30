// Package db provides the pgx connection pool and the per-transaction
// tenant-context helper that every RLS-protected query must go through.
package db

import (
	"context"
	"fmt"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgxpool"
)

type DB struct {
	Pool *pgxpool.Pool
}

func Open(ctx context.Context, databaseURL string) (*DB, error) {
	pool, err := pgxpool.New(ctx, databaseURL)
	if err != nil {
		return nil, fmt.Errorf("db: open pool: %w", err)
	}
	if err := pool.Ping(ctx); err != nil {
		pool.Close()
		return nil, fmt.Errorf("db: ping: %w", err)
	}
	return &DB{Pool: pool}, nil
}

func (d *DB) Close() {
	d.Pool.Close()
}

// TenantCtx carries the RLS session context for one request or job.
type TenantCtx struct {
	TenantID  uuid.UUID
	ActorID   uuid.UUID // zero value when acting as a system/job (no app.actor_id set)
	TeacherID uuid.UUID
	RequestID string
}

// WithTenantTx opens a transaction, drops to the non-owner yanai_app role,
// sets the RLS session GUCs (app.tenant_id / app.actor_id / app.request_id)
// via SET LOCAL semantics, runs fn, and commits. SET LOCAL guarantees the
// role and GUCs evaporate at commit/rollback, so pooled connections can
// never leak tenant context between requests or jobs.
func (d *DB) WithTenantTx(ctx context.Context, tc TenantCtx, fn func(tx pgx.Tx) error) error {
	tx, err := d.Pool.Begin(ctx)
	if err != nil {
		return fmt.Errorf("db: begin tx: %w", err)
	}
	defer tx.Rollback(ctx) //nolint:errcheck // no-op after commit

	if _, err := tx.Exec(ctx, "set local role yanai_app"); err != nil {
		return fmt.Errorf("db: set role: %w", err)
	}

	actorID := ""
	if tc.ActorID != uuid.Nil {
		actorID = tc.ActorID.String()
	}
	if _, err := tx.Exec(ctx,
		`select set_config('app.tenant_id', $1, true),
		        set_config('app.actor_id', $2, true),
		        set_config('app.request_id', $3, true)`,
		tc.TenantID.String(), actorID, tc.RequestID,
	); err != nil {
		return fmt.Errorf("db: set session context: %w", err)
	}

	if err := fn(tx); err != nil {
		return err
	}
	return tx.Commit(ctx)
}

// WithSystemTx opens a transaction as the pool owner (bypasses RLS). Use
// only for genuinely cross-tenant maintenance work (the worker's dispatch of
// a nil-tenant job) — never for handling request data.
func (d *DB) WithSystemTx(ctx context.Context, fn func(tx pgx.Tx) error) error {
	tx, err := d.Pool.Begin(ctx)
	if err != nil {
		return fmt.Errorf("db: begin system tx: %w", err)
	}
	defer tx.Rollback(ctx) //nolint:errcheck

	if err := fn(tx); err != nil {
		return err
	}
	return tx.Commit(ctx)
}
