package repo_test

import (
	"context"
	"errors"
	"net/http"
	"testing"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgconn"

	"mawta-server/internal/dbtest"
	"mawta-server/internal/repo"
)

// Tests for "one active term per stage" (index terms_one_active_key)
// and for ResolveTerm, the default term every class screen reads.
//
// The fixture year (YearA) has Bimestre I closed and Bimestre II active, both
// with no stage, and Quispe's Matemática 5B is a secundaria class.

// insertTerm inserts a term into the fixture year. A closed term needs its
// closed_at (terms_closed_consistent).
func insertTerm(t *testing.T, ctx context.Context, tx pgx.Tx, yearID uuid.UUID,
	stage *string, sequence int, startsOn, endsOn, status string) (uuid.UUID, error) {
	t.Helper()
	var id uuid.UUID
	err := tx.QueryRow(ctx, `
		insert into terms (tenant_id, academic_year_id, stage, sequence, name, starts_on, ends_on, status, closed_at)
		values (app.current_tenant_id(), $1, $2, $3::smallint, 'Periodo ' || $3::text, $4, $5, $6::text,
		        case when $6::text in ('closed', 'archived') then now() end)
		returning id
	`, yearID, stage, sequence, startsOn, endsOn, status).Scan(&id)
	return id, err
}

func mustInsertTerm(t *testing.T, ctx context.Context, tx pgx.Tx, yearID uuid.UUID,
	stage *string, sequence int, startsOn, endsOn, status string) uuid.UUID {
	t.Helper()
	id, err := insertTerm(t, ctx, tx, yearID, stage, sequence, startsOn, endsOn, status)
	if err != nil {
		t.Fatalf("insert term %d (%s): %v", sequence, status, err)
	}
	return id
}

func isUniqueViolation(err error) bool {
	var pg *pgconn.PgError
	return errors.As(err, &pg) && pg.Code == "23505"
}

// ------------------------------------------------ one active term per stage --

func TestOnlyOneActiveTermPerStage(t *testing.T) {
	env := dbtest.Setup(t)
	fx := env.Fx

	inTx(t, env, func(ctx context.Context, tx pgx.Tx) {
		// Bimestre II is already active with no stage: a second one is rejected.
		err := probe(t, ctx, tx, func() error {
			_, err := insertTerm(t, ctx, tx, fx.YearA, nil, 3, "2026-08-01", "2026-09-30", "active")
			return err
		})
		if !isUniqueViolation(err) {
			t.Errorf("a second active term of the same stage: err = %v, want unique violation", err)
		}

		// Another stage has its own active term, but only one.
		mustInsertTerm(t, ctx, tx, fx.YearA, str("primaria"), 1, "2026-03-01", "2026-05-15", "active")
		mustInsertTerm(t, ctx, tx, fx.YearA, str("secundaria"), 1, "2026-03-01", "2026-05-15", "active")
		err = probe(t, ctx, tx, func() error {
			_, err := insertTerm(t, ctx, tx, fx.YearA, str("primaria"), 2, "2026-05-16", "2026-07-31", "active")
			return err
		})
		if !isUniqueViolation(err) {
			t.Errorf("a second active primaria term: err = %v, want unique violation", err)
		}

		// planned, closed and archived are not limited.
		mustInsertTerm(t, ctx, tx, fx.YearA, nil, 3, "2026-08-01", "2026-09-30", "planned")
		mustInsertTerm(t, ctx, tx, fx.YearA, nil, 4, "2026-10-01", "2026-10-31", "planned")
		mustInsertTerm(t, ctx, tx, fx.YearA, nil, 5, "2026-11-01", "2026-11-30", "closed")
		mustInsertTerm(t, ctx, tx, fx.YearA, nil, 6, "2026-12-01", "2026-12-18", "archived")
	})
}

// A soft-deleted active term frees the slot, and so does closing it.
func TestActiveTermSlotIsFreedByDeletingOrClosing(t *testing.T) {
	env := dbtest.Setup(t)
	fx := env.Fx

	inTx(t, env, func(ctx context.Context, tx pgx.Tx) {
		next := mustInsertTerm(t, ctx, tx, fx.YearA, nil, 3, "2026-08-01", "2026-09-30", "planned")

		// Promoting while Bimestre II is still active is the strict relevo
		// failing: close first, then activate.
		err := probe(t, ctx, tx, func() error {
			_, err := tx.Exec(ctx, `update terms set status = 'active' where id = $1`, next)
			return err
		})
		if !isUniqueViolation(err) {
			t.Errorf("activating a term while another is active: err = %v, want unique violation", err)
		}

		if _, err := tx.Exec(ctx, `update terms set status = 'closed', closed_at = now() where id = $1`, fx.TermII); err != nil {
			t.Fatalf("close the active term: %v", err)
		}
		if _, err := tx.Exec(ctx, `update terms set status = 'active' where id = $1`, next); err != nil {
			t.Errorf("activating after closing the previous one: %v", err)
		}

		// A deleted active term does not block another one.
		if _, err := tx.Exec(ctx, `update terms set deleted_at = now() where id = $1`, next); err != nil {
			t.Fatalf("soft-delete: %v", err)
		}
		if _, err := insertTerm(t, ctx, tx, fx.YearA, nil, 4, "2026-10-01", "2026-10-31", "active"); err != nil {
			t.Errorf("a deleted active term still blocked a new one: %v", err)
		}
	})
}

// ---------------------------------------------------------- ResolveTerm --

func resolved(t *testing.T, ctx context.Context, tx pgx.Tx, classID, termID uuid.UUID) uuid.UUID {
	t.Helper()
	term, err := repo.ResolveTerm(ctx, tx, classID, termID)
	if err != nil {
		t.Fatalf("ResolveTerm: %v", err)
	}
	return term.ID
}

func TestResolveTermDefaultsToTheActiveTermOfTheClass(t *testing.T) {
	env := dbtest.Setup(t)
	fx := env.Fx

	inTx(t, env, func(ctx context.Context, tx pgx.Tx) {
		if got := resolved(t, ctx, tx, fx.ClassMat5B, uuid.Nil); got != fx.TermII {
			t.Errorf("default term = %s, want the active Bimestre II", got)
		}

		// Many terms in the year, only one of them active: the choice does not
		// depend on row order. This is the bug that hid the planned evidence.
		mustInsertTerm(t, ctx, tx, fx.YearA, nil, 3, "2026-08-01", "2026-09-30", "planned")
		mustInsertTerm(t, ctx, tx, fx.YearA, nil, 4, "2026-10-01", "2026-10-31", "planned")
		if got := resolved(t, ctx, tx, fx.ClassMat5B, uuid.Nil); got != fx.TermII {
			t.Errorf("default term with planned terms around = %s, want Bimestre II", got)
		}

		// The profile has no class: the active term of the active year.
		if got := resolved(t, ctx, tx, uuid.Nil, uuid.Nil); got != fx.TermII {
			t.Errorf("tenant default term = %s, want Bimestre II", got)
		}
	})
}

func TestResolveTermIgnoresTheActiveTermOfAnotherStage(t *testing.T) {
	env := dbtest.Setup(t)
	fx := env.Fx

	inTx(t, env, func(ctx context.Context, tx pgx.Tx) {
		// Bimestre II becomes a primaria term: the secundaria class no longer
		// sees it, and falls back to what applies to it (Bimestre I, closed).
		if _, err := tx.Exec(ctx, `update terms set stage = 'primaria' where id = $1`, fx.TermII); err != nil {
			t.Fatal(err)
		}
		if got := resolved(t, ctx, tx, fx.ClassMat5B, uuid.Nil); got != fx.TermI {
			t.Errorf("default term = %s, want Bimestre I (the only term of its stage)", got)
		}

		// With its own active term it takes that one.
		own := mustInsertTerm(t, ctx, tx, fx.YearA, str("secundaria"), 2, "2026-05-16", "2026-07-31", "active")
		if got := resolved(t, ctx, tx, fx.ClassMat5B, uuid.Nil); got != own {
			t.Errorf("default term = %s, want the active secundaria term %s", got, own)
		}
	})
}

// With nobody active the teacher still has a term to read: the latest closed
// one, then a planned one. It is never an error and never an arbitrary pick.
func TestResolveTermFallsBackWhenNothingIsActive(t *testing.T) {
	env := dbtest.Setup(t)
	fx := env.Fx

	inTx(t, env, func(ctx context.Context, tx pgx.Tx) {
		if _, err := tx.Exec(ctx, `update terms set status = 'closed', closed_at = now() where id = $1`, fx.TermII); err != nil {
			t.Fatal(err)
		}
		mustInsertTerm(t, ctx, tx, fx.YearA, nil, 3, "2026-08-01", "2026-09-30", "planned")
		if got := resolved(t, ctx, tx, fx.ClassMat5B, uuid.Nil); got != fx.TermII {
			t.Errorf("no active term: default = %s, want the latest closed one (Bimestre II)", got)
		}
		if got := resolved(t, ctx, tx, uuid.Nil, uuid.Nil); got != fx.TermII {
			t.Errorf("no active term, tenant scope: default = %s, want Bimestre II", got)
		}

		// Nothing closed either: the first planned term.
		if _, err := tx.Exec(ctx, `
			update terms set status = 'planned', closed_at = null where id in ($1, $2)
		`, fx.TermI, fx.TermII); err != nil {
			t.Fatal(err)
		}
		if got := resolved(t, ctx, tx, fx.ClassMat5B, uuid.Nil); got != fx.TermI {
			t.Errorf("only planned terms: default = %s, want the earliest (Bimestre I)", got)
		}
	})
}

func TestResolveTermWithAnExplicitTerm(t *testing.T) {
	env := dbtest.Setup(t)
	fx := env.Fx

	notFound := func(t *testing.T, err error, what string) {
		t.Helper()
		if e := appErr(t, err); e.Status != http.StatusNotFound {
			t.Errorf("%s: status = %d, want 404", what, e.Status)
		}
	}

	inTx(t, env, func(ctx context.Context, tx pgx.Tx) {
		// A closed term of the class is readable when asked for by id.
		if got := resolved(t, ctx, tx, fx.ClassMat5B, fx.TermI); got != fx.TermI {
			t.Errorf("explicit term = %s, want Bimestre I", got)
		}
		_, err := repo.ResolveTerm(ctx, tx, fx.ClassMat5B, uuid.New())
		notFound(t, err, "unknown term")

		// A term of another academic year is not the class's.
		otherYear := uuid.New()
		if _, err := tx.Exec(ctx, `
			insert into academic_years (id, tenant_id, year, name, starts_on, ends_on, term_structure, status)
			values ($1, app.current_tenant_id(), 2031, '2031', '2031-03-01', '2031-12-18', 'bimestre', 'planned')
		`, otherYear); err != nil {
			t.Fatal(err)
		}
		foreign := mustInsertTerm(t, ctx, tx, otherYear, nil, 1, "2031-03-01", "2031-05-15", "planned")
		_, err = repo.ResolveTerm(ctx, tx, fx.ClassMat5B, foreign)
		notFound(t, err, "a term of another year")

		// A term of another stage is not the class's either, while a term with
		// no stage and one of its own stage are.
		primaria := mustInsertTerm(t, ctx, tx, fx.YearA, str("primaria"), 1, "2026-03-01", "2026-05-15", "planned")
		_, err = repo.ResolveTerm(ctx, tx, fx.ClassMat5B, primaria)
		notFound(t, err, "a term of another stage")
		own := mustInsertTerm(t, ctx, tx, fx.YearA, str("secundaria"), 1, "2026-03-01", "2026-05-15", "planned")
		if got := resolved(t, ctx, tx, fx.ClassMat5B, own); got != own {
			t.Errorf("a term of the class's own stage = %s, want %s", got, own)
		}

		// With no class (the profile) any term of the tenant is accepted.
		if got := resolved(t, ctx, tx, uuid.Nil, foreign); got != foreign {
			t.Errorf("explicit term without a class = %s, want %s", got, foreign)
		}
	})
}

// A planned term still takes scores: only closed and archived terms reject
// them. That is why onboarding can leave every term after the first planned
// and still load the historical evidence of a later one.
func TestPlannedTermAcceptsScoresButClosedDoesNot(t *testing.T) {
	env := dbtest.Setup(t)
	fx := env.Fx

	score := func(ctx context.Context, tx pgx.Tx) error {
		return probe(t, ctx, tx, func() error {
			_, _, _, err := repo.CreateScore(ctx, tx, fx.AssessmentNumeric, fx.Students[1], fx.TeacherQuispe,
				"graded", f64(15), nil)
			return err
		})
	}
	inTx(t, env, func(ctx context.Context, tx pgx.Tx) {
		var termID uuid.UUID
		if err := tx.QueryRow(ctx, `select term_id from assessments where id = $1`, fx.AssessmentNumeric).Scan(&termID); err != nil {
			t.Fatal(err)
		}
		if _, err := tx.Exec(ctx, `update terms set status = 'planned', closed_at = null where id = $1`, termID); err != nil {
			t.Fatal(err)
		}
		if err := score(ctx, tx); err != nil {
			t.Errorf("a score in a planned term was rejected: %v", err)
		}
	})
	inTx(t, env, func(ctx context.Context, tx pgx.Tx) {
		var termID uuid.UUID
		if err := tx.QueryRow(ctx, `select term_id from assessments where id = $1`, fx.AssessmentNumeric).Scan(&termID); err != nil {
			t.Fatal(err)
		}
		if _, err := tx.Exec(ctx, `update terms set status = 'closed', closed_at = now() where id = $1`, termID); err != nil {
			t.Fatal(err)
		}
		if err := score(ctx, tx); err == nil {
			t.Error("a score in a closed term was accepted")
		}
	})
}
