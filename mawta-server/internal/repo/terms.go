package repo

import (
	"context"
	"errors"
	"net/http"
	"time"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"

	"mawta-server/internal/db"
)

type Term struct {
	ID       uuid.UUID
	StartsOn time.Time
	EndsOn   time.Time
}

func termNotFound() error {
	return db.NewAppError(http.StatusNotFound, "not_found", "no se encontró el periodo")
}

// ResolveTerm returns the term identified by termID, if it belongs to the
// class (see below). With the zero UUID it
// returns the class's current term: the active term of the class's academic
// year and stage (a term with no stage applies to every stage).
//
// A stage with no active term is a valid state (between two terms, or at the
// end of the year), so rather than failing it falls back to the latest closed
// term, which the teacher can still read, and as a last resort to the first
// planned one. classID may be the zero UUID for screens that belong to the
// teacher and not to a class (the profile): the scope is then the tenant's
// active academic year, any stage.
//
// "At most one active term per stage" is enforced by terms_one_active_key, so
// the choice never depends on row order.
func ResolveTerm(ctx context.Context, tx pgx.Tx, classID, termID uuid.UUID) (Term, error) {
	var t Term
	if termID != uuid.Nil {
		// An explicit term must belong to the class: same academic year, and a
		// stage the class takes (a term with no stage applies to every stage).
		// Anything else is "not found", not an empty screen or a score filed in
		// a period the class never has. Without a class (the profile) any term
		// of the tenant will do.
		var yearID *uuid.UUID
		var stage *string
		if classID != uuid.Nil {
			cc, err := loadClassContext(ctx, tx, classID)
			if err != nil {
				return t, err
			}
			yearID, stage = &cc.YearID, &cc.Stage
		}
		err := tx.QueryRow(ctx, `
			select id, starts_on, ends_on from terms
			 where id = $1 and deleted_at is null
			   and ($2::uuid is null or academic_year_id = $2)
			   and ($3::text is null or stage is null or stage = $3)
		`, termID, yearID, stage).Scan(&t.ID, &t.StartsOn, &t.EndsOn)
		if errors.Is(err, pgx.ErrNoRows) {
			return t, termNotFound()
		}
		return t, err
	}

	var yearID *uuid.UUID
	var stage *string
	if classID != uuid.Nil {
		cc, err := loadClassContext(ctx, tx, classID)
		if err != nil {
			return t, err
		}
		yearID, stage = &cc.YearID, &cc.Stage
	} else {
		var id uuid.UUID
		err := tx.QueryRow(ctx, `
			select id from academic_years where status = 'active' and deleted_at is null
		`).Scan(&id)
		if errors.Is(err, pgx.ErrNoRows) {
			return t, termNotFound()
		}
		if err != nil {
			return t, err
		}
		yearID = &id
	}

	err := tx.QueryRow(ctx, `
		select id, starts_on, ends_on
		  from terms
		 where academic_year_id = $1 and deleted_at is null
		   and ($2::text is null or stage is null or stage = $2)
		 order by case status when 'active' then 0 when 'planned' then 2 else 1 end,
		          stage is null,
		          case when status = 'planned' then starts_on end,
		          ends_on desc
		 limit 1
	`, yearID, stage).Scan(&t.ID, &t.StartsOn, &t.EndsOn)
	if errors.Is(err, pgx.ErrNoRows) {
		return t, termNotFound()
	}
	return t, err
}
