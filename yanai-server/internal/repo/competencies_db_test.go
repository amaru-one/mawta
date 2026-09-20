package repo_test

import (
	"context"
	"testing"
	"time"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"

	"yanai-server/internal/dbtest"
	"yanai-server/internal/repo"
)

// ------------------------------------------------- nothing derives a level --

// The norm's central rule, and the one thing no database constraint enforces.
// AssertCompetencyLevel leaves suggested_level_id and computed_grade_id null
// on purpose: under RVM 094-2020 the level is the teacher's judgement, and a
// computed number sitting next to it is exactly the framing the norm moves
// away from. Only a test can hold this.
func TestAssertCompetencyLevelSuggestsNothing(t *testing.T) {
	env := dbtest.Setup(t)

	inTx(t, env, func(ctx context.Context, tx pgx.Tx) {
		id, err := repo.AssertCompetencyLevel(ctx, tx, env.Fx.ClassMat5B, env.Fx.Students[0],
			env.Fx.CompetencyC2, env.Fx.TermII, env.Fx.TeacherQuispe, "A", nil)
		if err != nil {
			t.Fatalf("AssertCompetencyLevel: %v", err)
		}

		var suggested, computed *uuid.UUID
		var assertedBy uuid.UUID
		var classID, yearID uuid.UUID
		if err := tx.QueryRow(ctx, `
			select suggested_level_id, computed_grade_id, asserted_by_id, class_id, academic_year_id
			  from competency_term_levels where id = $1`, id).
			Scan(&suggested, &computed, &assertedBy, &classID, &yearID); err != nil {
			t.Fatalf("read: %v", err)
		}

		if suggested != nil {
			t.Errorf("suggested_level_id = %v, want null — nothing may suggest a nivel de logro", *suggested)
		}
		if computed != nil {
			t.Errorf("computed_grade_id = %v, want null — the official record is derived from nothing", *computed)
		}
		if assertedBy != env.Fx.TeacherQuispe {
			t.Errorf("asserted_by_id = %s, want the asserting teacher", assertedBy)
		}
		// class_id is provenance: which class the teacher was looking at.
		if classID != env.Fx.ClassMat5B {
			t.Errorf("class_id = %s, want %s", classID, env.Fx.ClassMat5B)
		}
		// The academic year is taken from the class, not from the caller.
		if yearID != env.Fx.YearA {
			t.Errorf("academic_year_id = %s, want %s", yearID, env.Fx.YearA)
		}
	})
}

func TestAssertCompetencyLevelSupersedesThePrevious(t *testing.T) {
	env := dbtest.Setup(t)

	inTx(t, env, func(ctx context.Context, tx pgx.Tx) {
		first, err := repo.AssertCompetencyLevel(ctx, tx, env.Fx.ClassMat5B, env.Fx.Students[0],
			env.Fx.CompetencyC2, env.Fx.TermII, env.Fx.TeacherQuispe, "B", nil)
		if err != nil {
			t.Fatalf("first assertion: %v", err)
		}
		second, err := repo.AssertCompetencyLevel(ctx, tx, env.Fx.ClassMat5B, env.Fx.Students[0],
			env.Fx.CompetencyC2, env.Fx.TermII, env.Fx.TeacherQuispe, "AD", nil)
		if err != nil {
			t.Fatalf("second assertion: %v", err)
		}

		var supersedes *uuid.UUID
		if err := tx.QueryRow(ctx, `select supersedes_id from competency_term_levels where id = $1`, second).Scan(&supersedes); err != nil {
			t.Fatalf("read: %v", err)
		}
		if supersedes == nil || *supersedes != first {
			t.Errorf("supersedes_id = %v, want %s", supersedes, first)
		}

		var live int
		if err := tx.QueryRow(ctx, `
			select count(*) from competency_term_levels
			 where student_id = $1 and competency_id = $2 and term_id = $3
			   and superseded_at is null and deleted_at is null`,
			env.Fx.Students[0], env.Fx.CompetencyC2, env.Fx.TermII).Scan(&live); err != nil {
			t.Fatalf("count: %v", err)
		}
		if live != 1 {
			t.Errorf("live levels = %d, want 1", live)
		}
	})
}

func TestAssertCompetencyLevelRejectsAnUnknownLevel(t *testing.T) {
	env := dbtest.Setup(t)

	inTx(t, env, func(ctx context.Context, tx pgx.Tx) {
		_, err := repo.AssertCompetencyLevel(ctx, tx, env.Fx.ClassMat5B, env.Fx.Students[0],
			env.Fx.CompetencyC2, env.Fx.TermII, env.Fx.TeacherQuispe, "E", nil)
		if err == nil {
			t.Fatal("an unknown level code was accepted")
		}
	})
}

// "No desarrollada" and "en inicio" are different facts. A competencia nobody
// has judged must read as null, never as C — reporting an unjudged competencia
// as the lowest level would invent a failing judgement.
func TestAnUnassertedCompetencyReadsAsNullNotC(t *testing.T) {
	env := dbtest.Setup(t)

	inTx(t, env, func(ctx context.Context, tx pgx.Tx) {
		rows, err := repo.ListClassCompetencyLevels(ctx, tx, env.Fx.ClassMat5B, env.Fx.Students[0], env.Fx.TermII)
		if err != nil {
			t.Fatalf("ListClassCompetencyLevels: %v", err)
		}
		if len(rows) == 0 {
			t.Fatal("no competencies returned for the class")
		}
		for _, r := range rows {
			if r.Level != nil {
				t.Errorf("%s has level %q before anything was asserted, want null", r.Code, *r.Level)
			}
		}

		// And once asserted, it reads back.
		if _, err := repo.AssertCompetencyLevel(ctx, tx, env.Fx.ClassMat5B, env.Fx.Students[0],
			env.Fx.CompetencyC2, env.Fx.TermII, env.Fx.TeacherQuispe, "A", nil); err != nil {
			t.Fatalf("AssertCompetencyLevel: %v", err)
		}

		rows, err = repo.ListClassCompetencyLevels(ctx, tx, env.Fx.ClassMat5B, env.Fx.Students[0], env.Fx.TermII)
		if err != nil {
			t.Fatalf("ListClassCompetencyLevels: %v", err)
		}
		var found bool
		for _, r := range rows {
			if r.CompetencyID == env.Fx.CompetencyC2 {
				found = true
				if r.Level == nil || *r.Level != "A" {
					t.Errorf("MAT-C2 level = %v, want A", r.Level)
				}
			} else if r.Level != nil {
				t.Errorf("%s gained a level it was never given", r.Code)
			}
		}
		if !found {
			t.Error("MAT-C2 was not in the list")
		}
	})
}

// ------------------------------------------------------------- the roster --

// The roster is a fact about a date, not a set. A student who left is on it
// before they left and off it after, and asking as of an earlier date must
// still show them — that is what makes a past term's register readable.
func TestRosterIsScopedToADate(t *testing.T) {
	env := dbtest.Setup(t)

	inTx(t, env, func(ctx context.Context, tx pgx.Tx) {
		leaver := env.Fx.Students[4]
		const leftOn = "2026-06-01"

		if _, err := tx.Exec(ctx,
			`update section_memberships set left_on = $1, status = 'withdrawn' where student_id = $2`,
			leftOn, leaver); err != nil {
			t.Fatalf("withdraw a student: %v", err)
		}

		before, err := repo.RosterAsOf(ctx, tx, env.Fx.ClassMat5B, date(t, "2026-05-20"))
		if err != nil {
			t.Fatalf("RosterAsOf before: %v", err)
		}
		if len(before) != 5 || !contains(before, leaver) {
			t.Errorf("roster before the withdrawal = %d students, want 5 including the leaver", len(before))
		}

		after, err := repo.RosterAsOf(ctx, tx, env.Fx.ClassMat5B, date(t, "2026-06-15"))
		if err != nil {
			t.Fatalf("RosterAsOf after: %v", err)
		}
		if len(after) != 4 || contains(after, leaver) {
			t.Errorf("roster after the withdrawal = %d students, want 4 without the leaver", len(after))
		}

		// left_on is exclusive: the last day is not a day of membership.
		onTheDay, err := repo.RosterAsOf(ctx, tx, env.Fx.ClassMat5B, date(t, leftOn))
		if err != nil {
			t.Fatalf("RosterAsOf on the day: %v", err)
		}
		if contains(onTheDay, leaver) {
			t.Error("the leaver is still on the roster on their left_on date; the window should be half-open")
		}
	})
}

func TestListClassStudentsHonoursTheRosterDate(t *testing.T) {
	env := dbtest.Setup(t)

	inTx(t, env, func(ctx context.Context, tx pgx.Tx) {
		if _, err := tx.Exec(ctx,
			`update section_memberships set left_on = '2026-06-01', status = 'withdrawn' where student_id = $1`,
			env.Fx.Students[4]); err != nil {
			t.Fatalf("withdraw: %v", err)
		}

		students, err := repo.ListClassStudents(ctx, tx, env.Fx.ClassMat5B, &env.Fx.CompetencyC2, env.Fx.TermII, date(t, "2026-06-15"))
		if err != nil {
			t.Fatalf("ListClassStudents: %v", err)
		}
		if len(students) != 4 {
			t.Errorf("students = %d, want 4 after the withdrawal", len(students))
		}
		for _, s := range students {
			if s.Level != nil {
				t.Errorf("%s has a level before one was asserted, want null", s.FullName)
			}
		}
	})
}

// ---------------------------------------------------------------- jobs --

// EnqueueJob dedupes on (kind, unique_key) while a job is still live, so a
// burst of score writes produces one recompute rather than a queue full of
// identical work.
func TestEnqueueJobDedupesOnUniqueKey(t *testing.T) {
	env := dbtest.Setup(t)

	inTx(t, env, func(ctx context.Context, tx pgx.Tx) {
		const key = "grade.recompute:test-key"
		for i := 0; i < 3; i++ {
			if err := repo.EnqueueJob(ctx, tx, env.Fx.TenantA, "grade.recompute", 2, []byte(`{}`), key); err != nil {
				t.Fatalf("EnqueueJob %d: %v", i, err)
			}
		}

		var n int
		var queue string
		if err := tx.QueryRow(ctx,
			`select count(*), min(queue) from jobs where kind = 'grade.recompute' and unique_key = $1`, key).
			Scan(&n, &queue); err != nil {
			t.Fatalf("count jobs: %v", err)
		}
		if n != 1 {
			t.Errorf("jobs enqueued = %d, want 1", n)
		}
		// The worker only polls 'default'; anything else is never claimed.
		if queue != "default" {
			t.Errorf("queue = %q, want default", queue)
		}
	})
}

// The enqueue rides the same transaction as the write that caused it, so a
// rolled-back score cannot leave a recompute behind for work that never
// happened.
func TestEnqueueRollsBackWithItsTransaction(t *testing.T) {
	env := dbtest.Setup(t)
	ctx := context.Background()
	const key = "grade.recompute:rollback-probe"

	tx, err := env.App.Pool.Begin(ctx)
	if err != nil {
		t.Fatalf("begin: %v", err)
	}
	if err := repo.EnqueueJob(ctx, tx, env.Fx.TenantA, "grade.recompute", 2, []byte(`{}`), key); err != nil {
		t.Fatalf("EnqueueJob: %v", err)
	}
	if err := tx.Rollback(ctx); err != nil {
		t.Fatalf("rollback: %v", err)
	}

	// jobs has no RLS policy, so this reads it directly.
	var n int
	if err := env.App.Pool.QueryRow(ctx, `select count(*) from jobs where unique_key = $1`, key).Scan(&n); err != nil {
		t.Fatalf("count jobs: %v", err)
	}
	if n != 0 {
		t.Errorf("a rolled-back transaction left %d job(s) behind", n)
	}
}

// ------------------------------------------------------------- helpers --

func date(t *testing.T, s string) time.Time {
	t.Helper()
	d, err := time.Parse("2006-01-02", s)
	if err != nil {
		t.Fatalf("parse date %q: %v", s, err)
	}
	return d
}

func contains(ids []uuid.UUID, want uuid.UUID) bool {
	for _, id := range ids {
		if id == want {
			return true
		}
	}
	return false
}
