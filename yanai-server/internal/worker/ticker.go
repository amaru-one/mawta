package worker

import (
	"context"
	"encoding/json"
	"log/slog"
	"time"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"

	"yanai-server/internal/db"
	"yanai-server/internal/domain"
	"yanai-server/internal/repo"
)

const tickerInterval = 10 * time.Minute

// tickerLoop periodically enqueues tenant-scoped maintenance jobs. Tenant
// enumeration runs as the pool owner (bypassing RLS) — the one deliberate
// use of that privilege, confined to this scheduler.
func tickerLoop(ctx context.Context, database *db.DB, logger *slog.Logger) {
	runSweepEnqueue(ctx, database, logger)
	t := time.NewTicker(tickerInterval)
	defer t.Stop()
	for {
		select {
		case <-ctx.Done():
			return
		case <-t.C:
			runSweepEnqueue(ctx, database, logger)
		}
	}
}

func runSweepEnqueue(ctx context.Context, database *db.DB, logger *slog.Logger) {
	rows, err := database.Pool.Query(ctx, `select id from tenants where status = 'active' and deleted_at is null`)
	if err != nil {
		logger.Error("worker: enumerate tenants", "error", err)
		return
	}
	var tenantIDs []uuid.UUID
	for rows.Next() {
		var id uuid.UUID
		if err := rows.Scan(&id); err != nil {
			rows.Close()
			logger.Error("worker: scan tenant", "error", err)
			return
		}
		tenantIDs = append(tenantIDs, id)
	}
	rows.Close()
	if err := rows.Err(); err != nil {
		logger.Error("worker: enumerate tenants", "error", err)
		return
	}

	today := time.Now().UTC().Format("2006-01-02")
	for _, tenantID := range tenantIDs {
		err := database.WithSystemTx(ctx, func(tx pgx.Tx) error {
			payload, _ := json.Marshal(map[string]any{"tenant_id": tenantID})
			if err := repo.EnqueueJob(ctx, tx, tenantID, domain.JobKindNotificationSweep, 4, payload, "notification.sweep:"+tenantID.String()+":"+today); err != nil {
				return err
			}
			return repo.EnqueueJob(ctx, tx, tenantID, domain.JobKindRetentionSweep, 4, payload, "retention.sweep:"+tenantID.String()+":"+today)
		})
		if err != nil {
			logger.Error("worker: enqueue sweep", "tenant_id", tenantID, "error", err)
		}
	}
}
