package repo

import (
	"context"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"
)

type FlagType struct {
	ID         uuid.UUID `json:"id"`
	Code       string    `json:"code"`
	Label      string    `json:"label"`
	Severity   string    `json:"severity"`
	IsPositive bool      `json:"is_positive"`
}

// ListFlagTypes returns the tenant's active behavior flag types in display order.
func ListFlagTypes(ctx context.Context, tx pgx.Tx) ([]FlagType, error) {
	rows, err := tx.Query(ctx, `
		select id, code, label, severity, is_positive
		  from behavior_flag_types
		 where is_active and deleted_at is null
		 order by sort_order, code
	`)
	if err != nil {
		return nil, err
	}
	defer rows.Close()

	var out []FlagType
	for rows.Next() {
		var ft FlagType
		if err := rows.Scan(&ft.ID, &ft.Code, &ft.Label, &ft.Severity, &ft.IsPositive); err != nil {
			return nil, err
		}
		out = append(out, ft)
	}
	return out, rows.Err()
}
