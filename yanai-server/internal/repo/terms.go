package repo

import (
	"context"
	"time"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"
)

type Term struct {
	ID       uuid.UUID
	StartsOn time.Time
	EndsOn   time.Time
}

// ResolveTerm returns the term identified by termID, or the tenant's single
// active term when termID is the zero UUID.
func ResolveTerm(ctx context.Context, tx pgx.Tx, termID uuid.UUID) (Term, error) {
	var t Term
	var err error
	if termID == uuid.Nil {
		err = tx.QueryRow(ctx, `
			select id, starts_on, ends_on from terms
			 where status = 'active' and deleted_at is null
			 limit 1
		`).Scan(&t.ID, &t.StartsOn, &t.EndsOn)
	} else {
		err = tx.QueryRow(ctx, `
			select id, starts_on, ends_on from terms
			 where id = $1 and deleted_at is null
		`, termID).Scan(&t.ID, &t.StartsOn, &t.EndsOn)
	}
	return t, err
}
