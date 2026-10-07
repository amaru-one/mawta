package repo_test

import (
	"context"
	"errors"
	"net/http"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgconn"

	"mawta-server/internal/dbtest"
	"mawta-server/internal/repo"
)

// Tests for "one active term per stage" (migrations/00007_one_active_term.sql)
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

	inTx(t, env, func(ctx context.Context, tx pgx.Tx) {
		// A closed term is readable when asked for by id.
		if got := resolved(t, ctx, tx, fx.ClassMat5B, fx.TermI); got != fx.TermI {
			t.Errorf("explicit term = %s, want Bimestre I", got)
		}
		_, err := repo.ResolveTerm(ctx, tx, fx.ClassMat5B, uuid.New())
		if e := appErr(t, err); e.Status != http.StatusNotFound {
			t.Errorf("unknown term: status = %d, want 404", e.Status)
		}
	})
}

// ------------------------------------------------- normalization migration --

// normalizeSQL is the data fix of migration 00007, taken from the file so the
// test runs the real statement. current_date is pinned so each case can say
// what "today" is.
func normalizeSQL(t *testing.T, today string) string {
	t.Helper()
	b, err := os.ReadFile(filepath.Join("..", "..", "migrations", "00007_one_active_term.sql"))
	if err != nil {
		t.Fatal(err)
	}
	s := string(b)
	from := strings.Index(s, "with active as")
	to := strings.Index(s, "create unique index terms_one_active_key")
	if from < 0 || to < 0 {
		t.Fatal("migration 00007 no longer has the normalization statement this test extracts")
	}
	return strings.ReplaceAll(s[from:to], "current_date", "date '"+today+"'")
}

func TestNormalizationKeepsOneActiveTermPerStage(t *testing.T) {
	env := dbtest.Setup(t)
	fx := env.Fx

	cases := []struct {
		name  string
		today string
		want  [3]string // statuses of terms I, II and III
	}{
		{"today inside the last term", "2026-10-07", [3]string{"closed", "closed", "active"}},
		{"today inside the first term", "2026-04-10", [3]string{"active", "planned", "planned"}},
		{"today in the gap between two terms", "2026-08-29", [3]string{"closed", "closed", "active"}},
		{"today after the year", "2027-01-10", [3]string{"closed", "closed", "active"}},
		{"today before the year", "2026-01-05", [3]string{"active", "planned", "planned"}},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			ctx := context.Background()
			tx, err := env.Admin.Pool.Begin(ctx)
			if err != nil {
				t.Fatal(err)
			}
			defer tx.Rollback(ctx) //nolint:errcheck

			// The index is what the migration creates after fixing the data, so
			// the old state (everything active) only exists without it.
			if _, err := tx.Exec(ctx, `drop index terms_one_active_key`); err != nil {
				t.Fatal(err)
			}
			if _, err := tx.Exec(ctx, `
				select set_config('app.tenant_id', $1, true)`, fx.TenantA.String()); err != nil {
				t.Fatal(err)
			}
			year := uuid.New()
			if _, err := tx.Exec(ctx, `
				insert into academic_years (id, tenant_id, year, name, starts_on, ends_on, term_structure, status)
				values ($1, $2, 2031, '2031', '2031-03-01', '2031-12-18', 'trimestre', 'planned')
			`, year, fx.TenantA); err != nil {
				t.Fatal(err)
			}
			// Every term of the year active, as onboarding used to leave them;
			// the dates are shifted to the 2026 calendar of the case below.
			ids := make([]uuid.UUID, 3)
			for i, d := range [][2]string{{"2026-03-02", "2026-05-29"}, {"2026-06-01", "2026-08-28"}, {"2026-08-31", "2026-12-18"}} {
				ids[i] = uuid.New()
				if _, err := tx.Exec(ctx, `
					insert into terms (id, tenant_id, academic_year_id, sequence, name, starts_on, ends_on, status)
					values ($1, $2, $3, $4::smallint, 'T' || $4::text, $5, $6, 'active')
				`, ids[i], fx.TenantA, year, i+1, d[0], d[1]); err != nil {
					t.Fatal(err)
				}
			}

			status := func() (got [3]string, closedAt [3]bool) {
				for i, id := range ids {
					var s string
					var c bool
					if err := tx.QueryRow(ctx, `select status, closed_at is not null from terms where id = $1`, id).Scan(&s, &c); err != nil {
						t.Fatal(err)
					}
					got[i], closedAt[i] = s, c
				}
				return
			}
			for pass := 1; pass <= 2; pass++ { // the second pass proves it is idempotent
				if _, err := tx.Exec(ctx, normalizeSQL(t, tc.today)); err != nil {
					t.Fatalf("normalize (pass %d): %v", pass, err)
				}
				got, closedAt := status()
				if got != tc.want {
					t.Errorf("pass %d: statuses = %v, want %v", pass, got, tc.want)
				}
				for i := range got {
					if (got[i] == "closed") != closedAt[i] {
						t.Errorf("pass %d: term %d is %s but closed_at set = %v", pass, i+1, got[i], closedAt[i])
					}
				}
			}
			// The index can be created on the normalized data.
			if _, err := tx.Exec(ctx, `
				create unique index terms_one_active_key on terms (academic_year_id, coalesce(stage, ''))
				 where status = 'active' and deleted_at is null`); err != nil {
				t.Errorf("the normalized data still violates the index: %v", err)
			}
		})
	}
}

func TestNormalizationTreatsEachStageOnItsOwn(t *testing.T) {
	env := dbtest.Setup(t)
	fx := env.Fx
	ctx := context.Background()

	tx, err := env.Admin.Pool.Begin(ctx)
	if err != nil {
		t.Fatal(err)
	}
	defer tx.Rollback(ctx) //nolint:errcheck
	if _, err := tx.Exec(ctx, `drop index terms_one_active_key`); err != nil {
		t.Fatal(err)
	}
	year := uuid.New()
	if _, err := tx.Exec(ctx, `
		insert into academic_years (id, tenant_id, year, name, starts_on, ends_on, term_structure, status)
		values ($1, $2, 2031, '2031', '2031-03-01', '2031-12-18', 'bimestre', 'planned')
	`, year, fx.TenantA); err != nil {
		t.Fatal(err)
	}
	// Primaria runs trimestres, secundaria bimestres, all active. Today is
	// 2026-07-10: inside primaria's second term and secundaria's third.
	insert := func(stage string, seq int, from, to string) uuid.UUID {
		id := uuid.New()
		if _, err := tx.Exec(ctx, `
			insert into terms (id, tenant_id, academic_year_id, stage, sequence, name, starts_on, ends_on, status)
			values ($1, $2, $3, $4, $5::smallint, 'T' || $5::text, $6, $7, 'active')
		`, id, fx.TenantA, year, stage, seq, from, to); err != nil {
			t.Fatal(err)
		}
		return id
	}
	p1 := insert("primaria", 1, "2026-03-02", "2026-05-29")
	p2 := insert("primaria", 2, "2026-06-01", "2026-08-28")
	s1 := insert("secundaria", 1, "2026-03-02", "2026-04-30")
	s2 := insert("secundaria", 2, "2026-05-01", "2026-06-15")
	s3 := insert("secundaria", 3, "2026-06-16", "2026-08-28")

	if _, err := tx.Exec(ctx, normalizeSQL(t, "2026-07-10")); err != nil {
		t.Fatal(err)
	}
	for id, want := range map[uuid.UUID]string{
		p1: "closed", p2: "active", s1: "closed", s2: "closed", s3: "active",
	} {
		var got string
		if err := tx.QueryRow(ctx, `select status from terms where id = $1`, id).Scan(&got); err != nil {
			t.Fatal(err)
		}
		if got != want {
			t.Errorf("term %s = %s, want %s", id, got, want)
		}
	}
	// The fixture's own year was already right and is left alone.
	var status string
	if err := tx.QueryRow(ctx, `select status from terms where id = $1`, fx.TermI).Scan(&status); err != nil || status != "closed" {
		t.Errorf("fixture Bimestre I = %q (%v), want closed", status, err)
	}
	if err := tx.QueryRow(ctx, `select status from terms where id = $1`, fx.TermII).Scan(&status); err != nil || status != "active" {
		t.Errorf("fixture Bimestre II = %q (%v), want active", status, err)
	}
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
				"graded", f64(15), 0)
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
