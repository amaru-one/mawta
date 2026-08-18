// Package handlers implements the per-kind job handlers dispatched by
// internal/worker's registry. Each handler takes plain arguments (job id,
// raw JSON payload) rather than a worker.Job, so this package never needs
// to import worker — avoiding an import cycle back through the registry.
package handlers

import (
	"context"
	"time"

	"github.com/jackc/pgx/v5"
)

// tenantToday returns "today" in the current session's tenant timezone.
func tenantToday(ctx context.Context, tx pgx.Tx) (time.Time, error) {
	var d time.Time
	err := tx.QueryRow(ctx, `
		select (now() at time zone tn.timezone)::date
		  from tenants tn where tn.id = app.current_tenant_id()
	`).Scan(&d)
	return d, err
}
