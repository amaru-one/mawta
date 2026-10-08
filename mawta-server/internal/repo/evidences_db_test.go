package repo_test

import (
	"context"
	"errors"
	"os"
	"testing"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgconn"

	"mawta-server/internal/db"
	"mawta-server/internal/dbtest"
	"mawta-server/internal/repo"
)

func TestMain(m *testing.M) { os.Exit(dbtest.Main(m)) }

func quispe(env *dbtest.Env) db.TenantCtx {
	return db.TenantCtx{
		TenantID:  env.Fx.TenantA,
		ActorID:   env.Fx.UserQuispe,
		TeacherID: env.Fx.TeacherQuispe,
		RequestID: "test",
		Role:      "teacher",
	}
}

// inTx runs fn inside a tenant transaction that is always rolled back, so each
// test sees the pristine fixture. The rollback is what makes these tests
// order-independent — there is no cleanup to forget.
func inTx(t *testing.T, env *dbtest.Env, fn func(ctx context.Context, tx pgx.Tx)) {
	t.Helper()
	ctx := context.Background()

	tx, err := env.App.Pool.Begin(ctx)
	if err != nil {
		t.Fatalf("begin: %v", err)
	}
	defer tx.Rollback(ctx) //nolint:errcheck

	tc := quispe(env)
	if _, err := tx.Exec(ctx, "set local role mawta_app"); err != nil {
		t.Fatalf("set role: %v", err)
	}
	if _, err := tx.Exec(ctx,
		`select set_config('app.tenant_id', $1, true),
		        set_config('app.actor_id', $2, true),
		        set_config('app.request_id', $3, true)`,
		tc.TenantID.String(), tc.ActorID.String(), tc.RequestID); err != nil {
		t.Fatalf("set tenant context: %v", err)
	}

	fn(ctx, tx)
}

func appErr(t *testing.T, err error) *db.AppError {
	t.Helper()
	if err == nil {
		t.Fatal("expected an error, got nil")
	}
	var ae *db.AppError
	if !errors.As(err, &ae) {
		t.Fatalf("expected an *AppError, got %T: %v", err, err)
	}
	return ae
}

func requireCode(t *testing.T, err error, status int, code string) {
	t.Helper()
	ae := appErr(t, err)
	if ae.Status != status || ae.Code != code {
		t.Fatalf("got %d/%s (%s), want %d/%s", ae.Status, ae.Code, ae.Message, status, code)
	}
}

func f64(v float64) *float64 { return &v }
func str(v string) *string   { return &v }

// -------------------------------------------------------- append-only scores --

// A correction must never overwrite: the old row is stamped and kept, the new
// one points back at it. That chain is the whole audit trail of a grade.
func TestCorrectScoreSupersedesRatherThanOverwriting(t *testing.T) {
	env := dbtest.Setup(t)

	inTx(t, env, func(ctx context.Context, tx pgx.Tx) {
		newID, studentID, _, _, err := repo.CorrectScore(ctx, tx, env.Fx.ScoreOne, env.Fx.TeacherQuispe, f64(18), nil, nil)
		if err != nil {
			t.Fatalf("CorrectScore: %v", err)
		}
		if studentID != env.Fx.Students[0] {
			t.Errorf("student = %s, want %s", studentID, env.Fx.Students[0])
		}

		// The old row survives, stamped.
		var supersededAt *string
		if err := tx.QueryRow(ctx, `select superseded_at::text from scores where id = $1`, env.Fx.ScoreOne).Scan(&supersededAt); err != nil {
			t.Fatalf("read the old row: %v", err)
		}
		if supersededAt == nil {
			t.Error("the corrected row was not stamped superseded_at")
		}

		// The new row points back at it and carries the new value.
		var supersedes uuid.UUID
		var raw float64
		if err := tx.QueryRow(ctx, `select supersedes_id, raw_value from scores where id = $1`, newID).Scan(&supersedes, &raw); err != nil {
			t.Fatalf("read the new row: %v", err)
		}
		if supersedes != env.Fx.ScoreOne {
			t.Errorf("supersedes_id = %s, want %s", supersedes, env.Fx.ScoreOne)
		}
		if raw != 18 {
			t.Errorf("raw_value = %v, want 18", raw)
		}

		// Exactly one live row for the student on the evidence, so the partial unique index
		// still holds and reads cannot see two answers.
		var live int
		if err := tx.QueryRow(ctx, `
			select count(*) from scores
			 where assessment_id = $1 and student_id = $2
			   and superseded_at is null and deleted_at is null`,
			env.Fx.AssessmentNumeric, env.Fx.Students[0]).Scan(&live); err != nil {
			t.Fatalf("count live rows: %v", err)
		}
		if live != 1 {
			t.Errorf("live rows = %d, want 1", live)
		}
	})
}

// Two teachers correcting the same score: the second must be told to reload,
// not silently win or produce a second live row.
func TestCorrectingATwiceSupersededScoreIs409(t *testing.T) {
	env := dbtest.Setup(t)

	inTx(t, env, func(ctx context.Context, tx pgx.Tx) {
		if _, _, _, _, err := repo.CorrectScore(ctx, tx, env.Fx.ScoreOne, env.Fx.TeacherQuispe, f64(18), nil, nil); err != nil {
			t.Fatalf("first correction: %v", err)
		}

		_, _, _, _, err := repo.CorrectScore(ctx, tx, env.Fx.ScoreOne, env.Fx.TeacherQuispe, f64(12), nil, nil)
		requireCode(t, err, 409, "already_superseded")
	})
}

func TestCorrectScoreValueInheritance(t *testing.T) {
	env := dbtest.Setup(t)

	t.Run("a correction naming no value inherits the old one", func(t *testing.T) {
		inTx(t, env, func(ctx context.Context, tx pgx.Tx) {
			newID, _, _, _, err := repo.CorrectScore(ctx, tx, env.Fx.ScoreOne, env.Fx.TeacherQuispe, nil, nil, nil)
			if err != nil {
				t.Fatalf("CorrectScore: %v", err)
			}
			var raw *float64
			if err := tx.QueryRow(ctx, `select raw_value from scores where id = $1`, newID).Scan(&raw); err != nil {
				t.Fatalf("read: %v", err)
			}
			if raw == nil || *raw != 16 {
				t.Errorf("raw_value = %v, want the inherited 16", raw)
			}
		})
	})

	t.Run("a correction naming a value replaces it", func(t *testing.T) {
		inTx(t, env, func(ctx context.Context, tx pgx.Tx) {
			newID, _, _, _, err := repo.CorrectScore(ctx, tx, env.Fx.ScoreOne, env.Fx.TeacherQuispe, f64(9), nil, nil)
			if err != nil {
				t.Fatalf("CorrectScore: %v", err)
			}
			var raw *float64
			if err := tx.QueryRow(ctx, `select raw_value from scores where id = $1`, newID).Scan(&raw); err != nil {
				t.Fatalf("read: %v", err)
			}
			if raw == nil || *raw != 9 {
				t.Errorf("raw_value = %v, want 9", raw)
			}
		})
	})

	// The one that matters: a row saying nothing was handed in must not keep a
	// mark on it. The DB would reject it anyway (scores_value_matches_status),
	// which makes this belt and braces — but it is the branch a careless edit
	// would break first.
	t.Run("a status other than graded clears the value", func(t *testing.T) {
		inTx(t, env, func(ctx context.Context, tx pgx.Tx) {
			newID, _, _, _, err := repo.CorrectScore(ctx, tx, env.Fx.ScoreOne, env.Fx.TeacherQuispe, nil, nil, str("not_submitted"))
			if err != nil {
				t.Fatalf("CorrectScore: %v", err)
			}
			var raw *float64
			var status string
			if err := tx.QueryRow(ctx, `select raw_value, status from scores where id = $1`, newID).Scan(&raw, &status); err != nil {
				t.Fatalf("read: %v", err)
			}
			if status != "not_submitted" {
				t.Errorf("status = %q, want not_submitted", status)
			}
			if raw != nil {
				t.Errorf("raw_value = %v, want null — a not_submitted row must carry no mark", *raw)
			}
		})
	})
}

// The append-only rule is enforced by the database, not only by convention:
// even a direct UPDATE cannot rewrite a mark.
func TestScoresCannotBeUpdatedInPlace(t *testing.T) {
	env := dbtest.Setup(t)

	inTx(t, env, func(ctx context.Context, tx pgx.Tx) {
		_, err := tx.Exec(ctx, `update scores set raw_value = 20 where id = $1`, env.Fx.ScoreOne)
		if err == nil {
			t.Fatal("a score was updated in place")
		}
		var pgErr *pgconn.PgError
		if !errors.As(err, &pgErr) || pgErr.Code != "23001" {
			t.Errorf("got %v, want restrict_violation (23001) from forbid_score_mutation", err)
		}
	})
}

// ------------------------------------------------------------ value kinds --

// A numeric evidence takes a mark and nothing else; an ordinal one takes a
// level and nothing else. The Go check gives the teacher a sentence; the
// trigger in the database is the backstop.
func TestCreateScoreMatchesTheEvidenceScale(t *testing.T) {
	env := dbtest.Setup(t)

	t.Run("a level on a numeric evidence", func(t *testing.T) {
		inTx(t, env, func(ctx context.Context, tx pgx.Tx) {
			_, _, _, err := repo.CreateScore(ctx, tx, env.Fx.AssessmentNumeric, env.Fx.Students[1],
				env.Fx.TeacherQuispe, "graded", nil, str("A"))
			requireCode(t, err, 400, "level_on_numeric")
		})
	})

	t.Run("a mark on an ordinal evidence", func(t *testing.T) {
		inTx(t, env, func(ctx context.Context, tx pgx.Tx) {
			_, _, _, err := repo.CreateScore(ctx, tx, env.Fx.AssessmentOrdinal, env.Fx.Students[1],
				env.Fx.TeacherQuispe, "graded", f64(3), nil)
			requireCode(t, err, 400, "mark_on_ordinal")
		})
	})

	t.Run("a mark above the maximum", func(t *testing.T) {
		inTx(t, env, func(ctx context.Context, tx pgx.Tx) {
			_, _, _, err := repo.CreateScore(ctx, tx, env.Fx.AssessmentNumeric, env.Fx.Students[1],
				env.Fx.TeacherQuispe, "graded", f64(21), nil)
			requireCode(t, err, 400, "mark_out_of_range")
		})
	})

	t.Run("graded with no value", func(t *testing.T) {
		inTx(t, env, func(ctx context.Context, tx pgx.Tx) {
			_, _, _, err := repo.CreateScore(ctx, tx, env.Fx.AssessmentNumeric, env.Fx.Students[1],
				env.Fx.TeacherQuispe, "graded", nil, nil)
			requireCode(t, err, 400, "value_required")
		})
	})

	t.Run("a level outside AD/A/B/C", func(t *testing.T) {
		inTx(t, env, func(ctx context.Context, tx pgx.Tx) {
			_, _, _, err := repo.CreateScore(ctx, tx, env.Fx.AssessmentOrdinal, env.Fx.Students[1],
				env.Fx.TeacherQuispe, "graded", nil, str("A+"))
			requireCode(t, err, 400, "invalid_level")
		})
	})
}

// A level on an ordinal evidence is stored as the scale level, with no mark and
// no maximum. It is the valuation of that piece of work, not the nivel de logro.
func TestOrdinalScoreStoresTheLevelAndNoMark(t *testing.T) {
	env := dbtest.Setup(t)

	inTx(t, env, func(ctx context.Context, tx pgx.Tx) {
		id, _, _, err := repo.CreateScore(ctx, tx, env.Fx.AssessmentOrdinal, env.Fx.Students[0],
			env.Fx.TeacherQuispe, "graded", nil, str("A"))
		if err != nil {
			t.Fatalf("CreateScore: %v", err)
		}

		var raw, max *float64
		var levelID uuid.UUID
		if err := tx.QueryRow(ctx,
			`select raw_value, max_value, scale_level_id from scores where id = $1`, id).
			Scan(&raw, &max, &levelID); err != nil {
			t.Fatalf("read: %v", err)
		}
		if raw != nil || max != nil {
			t.Errorf("raw_value/max_value = %v/%v, want both null on a level-valued score", raw, max)
		}
		if levelID != env.Fx.LevelA {
			t.Errorf("scale_level_id = %s, want the A level %s", levelID, env.Fx.LevelA)
		}
	})
}

// A correction on an ordinal evidence replaces the level, and a second one on
// the same row is told to reload.
func TestCorrectOrdinalScore(t *testing.T) {
	env := dbtest.Setup(t)

	inTx(t, env, func(ctx context.Context, tx pgx.Tx) {
		original, _, _, err := repo.CreateScore(ctx, tx, env.Fx.AssessmentOrdinal, env.Fx.Students[0],
			env.Fx.TeacherQuispe, "graded", nil, str("B"))
		if err != nil {
			t.Fatalf("CreateScore: %v", err)
		}
		corrected, _, _, _, err := repo.CorrectScore(ctx, tx, original, env.Fx.TeacherQuispe, nil, str("AD"), nil)
		if err != nil {
			t.Fatalf("CorrectScore: %v", err)
		}
		var levelID uuid.UUID
		if err := tx.QueryRow(ctx, `select scale_level_id from scores where id = $1`, corrected).Scan(&levelID); err != nil {
			t.Fatalf("read: %v", err)
		}
		if levelID != env.Fx.LevelAD {
			t.Errorf("scale_level_id = %s, want AD", levelID)
		}

		_, _, _, _, err = repo.CorrectScore(ctx, tx, original, env.Fx.TeacherQuispe, nil, str("C"), nil)
		requireCode(t, err, 409, "already_superseded")
	})
}

// The database refuses a value that does not fit the scale even when the Go
// check is bypassed.
func TestDatabaseRejectsAValueOfTheWrongKind(t *testing.T) {
	env := dbtest.Setup(t)

	inTx(t, env, func(ctx context.Context, tx pgx.Tx) {
		_, err := tx.Exec(ctx, `
			insert into scores (tenant_id, assessment_id, student_id, status, scale_level_id, recorded_by_id)
			values (app.current_tenant_id(), $1, $2, 'graded', $3, $4)`,
			env.Fx.AssessmentNumeric, env.Fx.Students[1], env.Fx.LevelA, env.Fx.TeacherQuispe)
		if err == nil {
			t.Fatal("a level was stored on a numeric evidence")
		}
		var pgErr *pgconn.PgError
		if !errors.As(err, &pgErr) || pgErr.Code != "23514" {
			t.Errorf("got %v, want check_violation (23514)", err)
		}
	})
}

// ------------------------------------------------------------- evidences --

// An evidence reaches a competencia only through its criterios, so one without
// any is refused.
func TestCreateAssessmentRequiresACriterion(t *testing.T) {
	env := dbtest.Setup(t)

	inTx(t, env, func(ctx context.Context, tx pgx.Tx) {
		_, err := repo.CreateAssessment(ctx, tx, repo.NewAssessment{
			ClassID: env.Fx.ClassMat5B, TermID: env.Fx.TermII, TeacherID: env.Fx.TeacherQuispe,
			Title: "Sin criterio", Kind: "tarea", ValueScale: "numeric", MaxScore: f64(18),
		})
		requireCode(t, err, 400, "criteria_required")
	})
}

func TestCreateAssessmentKeepsItsOwnMaximum(t *testing.T) {
	env := dbtest.Setup(t)

	inTx(t, env, func(ctx context.Context, tx pgx.Tx) {
		id, err := repo.CreateAssessment(ctx, tx, repo.NewAssessment{
			ClassID: env.Fx.ClassMat5B, TermID: env.Fx.TermII, TeacherID: env.Fx.TeacherQuispe,
			Title: "Control", Kind: "tarea", ValueScale: "numeric", MaxScore: f64(18),
			CriterionIDs: []uuid.UUID{env.Fx.CriterionOne},
		})
		if err != nil {
			t.Fatalf("CreateAssessment: %v", err)
		}
		scoreID, _, _, err := repo.CreateScore(ctx, tx, id, env.Fx.Students[0], env.Fx.TeacherQuispe, "graded", f64(14), nil)
		if err != nil {
			t.Fatalf("CreateScore: %v", err)
		}
		var raw, max float64
		if err := tx.QueryRow(ctx, `select raw_value, max_value from scores where id = $1`, scoreID).Scan(&raw, &max); err != nil {
			t.Fatalf("read: %v", err)
		}
		if raw != 14 || max != 18 {
			t.Errorf("raw/max = %v/%v, want 14/18", raw, max)
		}
	})
}
