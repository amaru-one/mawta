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

		// Exactly one live row for the attempt, so the partial unique index
		// still holds and reads cannot see two answers.
		var live int
		if err := tx.QueryRow(ctx, `
			select count(*) from scores
			 where assessment_id = $1 and student_id = $2 and attempt_number = 1
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
			newID, _, _, _, err := repo.CorrectScore(ctx, tx, env.Fx.ScoreOne, env.Fx.TeacherQuispe, nil, nil, f64i(2))
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
			newID, _, _, _, err := repo.CorrectScore(ctx, tx, env.Fx.ScoreOne, env.Fx.TeacherQuispe, nil, str("not_submitted"), nil)
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

// --------------------------------------------------------- criterion scores --

func TestCreateCriterionScoreRejectsAmbiguousValues(t *testing.T) {
	env := dbtest.Setup(t)

	t.Run("a mark and a level together", func(t *testing.T) {
		inTx(t, env, func(ctx context.Context, tx pgx.Tx) {
			_, err := repo.CreateCriterionScore(ctx, tx, env.Fx.AssessmentRubric, env.Fx.CriterionOne,
				env.Fx.Students[0], env.Fx.TeacherQuispe, f64(3), str("A"))
			requireCode(t, err, 400, "two_values")
		})
	})

	t.Run("neither a mark nor a level", func(t *testing.T) {
		inTx(t, env, func(ctx context.Context, tx pgx.Tx) {
			_, err := repo.CreateCriterionScore(ctx, tx, env.Fx.AssessmentRubric, env.Fx.CriterionOne,
				env.Fx.Students[0], env.Fx.TeacherQuispe, nil, nil)
			requireCode(t, err, 400, "missing_value")
		})
	})

	t.Run("a level outside the ordinal scale", func(t *testing.T) {
		inTx(t, env, func(ctx context.Context, tx pgx.Tx) {
			_, err := repo.CreateCriterionScore(ctx, tx, env.Fx.AssessmentRubric, env.Fx.CriterionOne,
				env.Fx.Students[0], env.Fx.TeacherQuispe, nil, str("A+"))
			requireCode(t, err, 400, "unknown_level")
		})
	})
}

// A criterio CAN be marked by level — that is evidence, not a nivel de logro.
// The vocabulary differs from assessments on purpose: 'ordinal' here, 'rubric'
// there.
func TestCriterionScoreByLevelStoresOrdinalAndNoMax(t *testing.T) {
	env := dbtest.Setup(t)

	inTx(t, env, func(ctx context.Context, tx pgx.Tx) {
		id, err := repo.CreateCriterionScore(ctx, tx, env.Fx.AssessmentRubric, env.Fx.CriterionOne,
			env.Fx.Students[0], env.Fx.TeacherQuispe, nil, str("A"))
		if err != nil {
			t.Fatalf("CreateCriterionScore: %v", err)
		}

		var scale string
		var raw, max *float64
		var levelID uuid.UUID
		if err := tx.QueryRow(ctx,
			`select value_scale, raw_value, max_value, scale_level_id from criterion_scores where id = $1`, id).
			Scan(&scale, &raw, &max, &levelID); err != nil {
			t.Fatalf("read: %v", err)
		}

		if scale != "ordinal" {
			t.Errorf("value_scale = %q, want ordinal (not 'rubric' — that is the assessment's vocabulary)", scale)
		}
		if raw != nil || max != nil {
			t.Errorf("raw_value/max_value = %v/%v, want both null on a level-valued mark", raw, max)
		}
		if levelID != env.Fx.LevelA {
			t.Errorf("scale_level_id = %s, want the A level %s", levelID, env.Fx.LevelA)
		}
	})
}

// A rubric assessment carries no max_score, so there is nothing to mark out of.
// The teacher is told to use a level instead, rather than getting a raw
// constraint error.
func TestNumericCriterionScoreNeedsAMaxScore(t *testing.T) {
	env := dbtest.Setup(t)

	inTx(t, env, func(ctx context.Context, tx pgx.Tx) {
		_, err := repo.CreateCriterionScore(ctx, tx, env.Fx.AssessmentRubric, env.Fx.CriterionOne,
			env.Fx.Students[0], env.Fx.TeacherQuispe, f64(3), nil)
		requireCode(t, err, 400, "no_max_score")
	})
}

// The criterio has to have been tagged on the assessment. Checked in Go so the
// teacher gets a sentence rather than a composite FK violation.
func TestCriterionScoreRequiresTheCriterionToBeTagged(t *testing.T) {
	env := dbtest.Setup(t)

	inTx(t, env, func(ctx context.Context, tx pgx.Tx) {
		// The numeric assessment was deliberately left untagged.
		_, err := repo.CreateCriterionScore(ctx, tx, env.Fx.AssessmentNumeric, env.Fx.CriterionOne,
			env.Fx.Students[0], env.Fx.TeacherQuispe, f64(3), nil)
		requireCode(t, err, 400, "criterion_not_tagged")
	})
}

func TestCorrectCriterionScoreSupersedesAndRevalidates(t *testing.T) {
	env := dbtest.Setup(t)

	inTx(t, env, func(ctx context.Context, tx pgx.Tx) {
		original, err := repo.CreateCriterionScore(ctx, tx, env.Fx.AssessmentRubric, env.Fx.CriterionOne,
			env.Fx.Students[0], env.Fx.TeacherQuispe, nil, str("B"))
		if err != nil {
			t.Fatalf("CreateCriterionScore: %v", err)
		}

		corrected, err := repo.CorrectCriterionScore(ctx, tx, original, env.Fx.TeacherQuispe, nil, str("AD"))
		if err != nil {
			t.Fatalf("CorrectCriterionScore: %v", err)
		}

		var supersededAt *string
		if err := tx.QueryRow(ctx, `select superseded_at::text from criterion_scores where id = $1`, original).Scan(&supersededAt); err != nil {
			t.Fatalf("read the old row: %v", err)
		}
		if supersededAt == nil {
			t.Error("the corrected criterion score was not stamped")
		}

		var levelID uuid.UUID
		if err := tx.QueryRow(ctx, `select scale_level_id from criterion_scores where id = $1`, corrected).Scan(&levelID); err != nil {
			t.Fatalf("read the new row: %v", err)
		}
		if levelID != env.Fx.LevelAD {
			t.Errorf("scale_level_id = %s, want AD", levelID)
		}

		// A second correction of the same row is a 409, same protocol as scores.
		_, err = repo.CorrectCriterionScore(ctx, tx, original, env.Fx.TeacherQuispe, nil, str("C"))
		requireCode(t, err, 409, "already_superseded")
	})
}

// The correction path re-runs the value rules, so a correction cannot smuggle
// in a shape the create path would have rejected.
func TestCorrectCriterionScoreRejectsAmbiguousValues(t *testing.T) {
	env := dbtest.Setup(t)

	inTx(t, env, func(ctx context.Context, tx pgx.Tx) {
		original, err := repo.CreateCriterionScore(ctx, tx, env.Fx.AssessmentRubric, env.Fx.CriterionOne,
			env.Fx.Students[0], env.Fx.TeacherQuispe, nil, str("B"))
		if err != nil {
			t.Fatalf("CreateCriterionScore: %v", err)
		}

		_, err = repo.CorrectCriterionScore(ctx, tx, original, env.Fx.TeacherQuispe, f64(3), str("A"))
		requireCode(t, err, 400, "two_values")

		// And the original is still live: a rejected correction must not have
		// consumed it.
		var supersededAt *string
		if err := tx.QueryRow(ctx, `select superseded_at::text from criterion_scores where id = $1`, original).Scan(&supersededAt); err != nil {
			t.Fatalf("read: %v", err)
		}
		if supersededAt != nil {
			t.Error("a rejected correction still superseded the original")
		}
	})
}

func TestCriterionScoresCannotBeUpdatedInPlace(t *testing.T) {
	env := dbtest.Setup(t)

	inTx(t, env, func(ctx context.Context, tx pgx.Tx) {
		id, err := repo.CreateCriterionScore(ctx, tx, env.Fx.AssessmentRubric, env.Fx.CriterionOne,
			env.Fx.Students[0], env.Fx.TeacherQuispe, nil, str("B"))
		if err != nil {
			t.Fatalf("CreateCriterionScore: %v", err)
		}

		_, err = tx.Exec(ctx, `update criterion_scores set scale_level_id = $1 where id = $2`, env.Fx.LevelAD, id)
		if err == nil {
			t.Fatal("a criterion score was updated in place")
		}
		var pgErr *pgconn.PgError
		if !errors.As(err, &pgErr) || pgErr.Code != "23001" {
			t.Errorf("got %v, want restrict_violation (23001)", err)
		}
	})
}

func f64i(v int16) *int16 { return &v }
