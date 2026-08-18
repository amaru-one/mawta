package repo

import (
	"context"
	"time"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"
)

// RosterAsOf returns the student ids belonging to a class's section on date
// d — the canonical roster-as-of-date join used throughout the API.
func RosterAsOf(ctx context.Context, tx pgx.Tx, classID uuid.UUID, d time.Time) ([]uuid.UUID, error) {
	rows, err := tx.Query(ctx, `
		select sm.student_id
		  from section_memberships sm
		  join classes c on c.section_id = sm.section_id
		 where c.id = $1
		   and sm.joined_on <= $2
		   and (sm.left_on is null or sm.left_on > $2)
		   and sm.deleted_at is null
	`, classID, d)
	if err != nil {
		return nil, err
	}
	defer rows.Close()

	var ids []uuid.UUID
	for rows.Next() {
		var id uuid.UUID
		if err := rows.Scan(&id); err != nil {
			return nil, err
		}
		ids = append(ids, id)
	}
	return ids, rows.Err()
}
