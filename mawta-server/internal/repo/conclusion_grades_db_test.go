package repo_test

import (
	"context"
	"testing"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"

	"mawta-server/internal/dbtest"
	"mawta-server/internal/repo"
)

// A conclusion remembers when it was written: a score change in its
// competency after that flags it, so the teacher can save it again even when
// the text did not change. Same competency only.
func TestGradesChangedSinceConclusion(t *testing.T) {
	env := dbtest.Setup(t)
	fx := env.Fx
	student := fx.Students[0]

	inTx(t, env, func(ctx context.Context, tx pgx.Tx) {
		var competency, termID uuid.UUID
		if err := tx.QueryRow(ctx, `
			select ec.competency_id, s.term_id
			  from scores s
			  join assessment_criteria ac on ac.assessment_id = s.assessment_id
			  join evaluation_criteria ec on ec.id = ac.criterion_id
			 where s.id = $1
		`, fx.ScoreOne).Scan(&competency, &termID); err != nil {
			t.Fatalf("resolve the competency of ScoreOne: %v", err)
		}
		levelOf := func() repo.CompetencyLevelRow {
			rows, err := repo.ListClassCompetencyLevels(ctx, tx, fx.ClassMat5B, student, termID)
			if err != nil {
				t.Fatalf("ListClassCompetencyLevels: %v", err)
			}
			for _, r := range rows {
				if r.CompetencyID == competency {
					return r
				}
			}
			t.Fatal("competency missing from the class list")
			return repo.CompetencyLevelRow{}
		}

		if _, err := repo.UpsertConclusion(ctx, tx, fx.ClassMat5B, student, competency, termID, fx.TeacherQuispe,
			"Resuelve problemas con autonomía.", "draft", nil); err != nil {
			t.Fatalf("UpsertConclusion: %v", err)
		}
		// Every write in this transaction shares now(), and the fixture's
		// scores were written in an earlier one. Place the conclusion exactly
		// at the last existing change: nothing is later yet, and the correction
		// below (now()) is strictly later.
		if _, err := tx.Exec(ctx, `
			update descriptive_conclusions dc
			   set authored_at = (
			     select max(greatest(s.created_at, s.superseded_at, s.deleted_at))
			       from scores s
			       join assessment_criteria ac on ac.assessment_id = s.assessment_id
			       join evaluation_criteria ec on ec.id = ac.criterion_id
			      where s.student_id = $3 and s.term_id = $2 and ec.competency_id = $1)
			 where dc.competency_id = $1 and dc.term_id = $2 and dc.superseded_at is null
		`, competency, termID, student); err != nil {
			t.Fatalf("place conclusion at the last score change: %v", err)
		}
		if r := levelOf(); r.GradesChanged {
			t.Fatal("no score changed after the conclusion: grades_changed must be false")
		}

		value := 17.0
		if _, _, _, _, err := repo.CorrectScore(ctx, tx, fx.ScoreOne, fx.TeacherQuispe, &value, nil, nil); err != nil {
			t.Fatalf("CorrectScore: %v", err)
		}
		if r := levelOf(); !r.GradesChanged {
			t.Fatal("a corrected score after the conclusion must set grades_changed")
		}

		// Another competency's scores do not touch this conclusion's flag.
		if _, err := repo.UpsertConclusion(ctx, tx, fx.ClassMat5B, student, competency, termID, fx.TeacherQuispe,
			"Resuelve problemas con autonomía y claridad.", "draft", nil); err != nil {
			t.Fatalf("UpsertConclusion again: %v", err)
		}
		if r := levelOf(); r.GradesChanged {
			t.Fatal("a conclusion written after the last change must clear grades_changed")
		}
	})
}
