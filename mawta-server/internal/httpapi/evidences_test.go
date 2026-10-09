package httpapi_test

import (
	"context"
	"fmt"
	"math"
	"net/http"
	"testing"

	"mawta-server/internal/dbtest"
	"mawta-server/internal/repo"
)

// The whole path of valuing one piece of evidence, end to end: file it with a
// criterio and a scale, value a student on it, and read it back with the
// valuation attached.
func TestEvidenceIsFiledAndValued(t *testing.T) {
	env := dbtest.Setup(t)
	h := newAPI(t, env)
	token := login(t, env, env.Fx.UserQuispe, env.Fx.TenantA)
	fx := env.Fx
	class := fx.ClassMat5B.String()
	student := fx.Students[2].String()

	t.Cleanup(func() {
		ctx := context.Background()
		for _, q := range []string{
			`delete from scores where assessment_id in (select id from assessments where title like 'T-eval-%')`,
			`delete from assessment_criteria where assessment_id in (select id from assessments where title like 'T-eval-%')`,
			`delete from assessments where title like 'T-eval-%'`,
		} {
			if _, err := env.Admin.Pool.Exec(ctx, q); err != nil {
				t.Errorf("clean up: %v", err)
			}
		}
	})

	file := func(extra string) string {
		t.Helper()
		w := mustDo(t, h, token, "POST", "/api/v1/classes/"+class+"/assessments", fmt.Sprintf(
			`{"kind":"produccion","term_id":%q,"criterion_ids":[%q]%s}`, fx.TermII, fx.CriterionOne, extra), http.StatusCreated)
		var out struct {
			ID string `json:"id"`
		}
		decodeInto(t, w, &out)
		return out.ID
	}
	read := func(id string) repo.EvaluationEntry {
		t.Helper()
		w := mustDo(t, h, token, "GET", fmt.Sprintf("/api/v1/classes/%s/students/%s/evidence?term_id=%s",
			class, student, fx.TermII), "", http.StatusOK)
		var got struct {
			Evidence []repo.EvaluationEntry `json:"evidence"`
		}
		decodeInto(t, w, &got)
		for _, e := range got.Evidence {
			if e.AssessmentID.String() == id {
				return e
			}
		}
		t.Fatalf("evidence %s is not in the student's list", id)
		return repo.EvaluationEntry{}
	}

	t.Run("a numeric evidence out of its own maximum shows a percentage", func(t *testing.T) {
		id := file(`,"title":"T-eval-num","value_scale":"numeric","max_score":18`)
		if e := read(id); e.Score != nil || e.MaxScore == nil || *e.MaxScore != 18 {
			t.Fatalf("before valuing: score=%+v max=%v, want no score and max 18", e.Score, e.MaxScore)
		}
		mustDo(t, h, token, "POST", "/api/v1/assessments/"+id+"/scores", fmt.Sprintf(
			`{"student_id":%q,"raw_value":14}`, student), http.StatusCreated)
		e := read(id)
		if e.Score == nil || e.Score.RawValue == nil || *e.Score.RawValue != 14 {
			t.Fatalf("after valuing: score = %+v, want raw 14", e.Score)
		}
		if e.Score.Percentage == nil || math.Abs(*e.Score.Percentage-77.7778) > 0.01 {
			t.Errorf("percentage = %v, want 77.78", e.Score.Percentage)
		}
		if e.Score.Level != nil {
			t.Errorf("a numeric evidence carries level %q", *e.Score.Level)
		}
	})

	t.Run("an ordinal evidence takes a level, and a correction replaces it", func(t *testing.T) {
		id := file(`,"title":"T-eval-ord","value_scale":"ordinal"`)
		w := mustDo(t, h, token, "POST", "/api/v1/assessments/"+id+"/scores", fmt.Sprintf(
			`{"student_id":%q,"level":"B"}`, student), http.StatusCreated)
		var created struct {
			ID string `json:"id"`
		}
		decodeInto(t, w, &created)
		if e := read(id); e.Score == nil || e.Score.Level == nil || *e.Score.Level != "B" || e.Score.RawValue != nil {
			t.Fatalf("after valuing: score = %+v, want level B and no mark", e.Score)
		}
		mustDo(t, h, token, "POST", "/api/v1/scores/"+created.ID+"/correct", `{"level":"AD"}`, http.StatusCreated)
		if e := read(id); e.Score == nil || e.Score.Level == nil || *e.Score.Level != "AD" {
			t.Fatalf("after correcting: score = %+v, want level AD", e.Score)
		}
	})

	t.Run("a value of the wrong kind is refused", func(t *testing.T) {
		num := file(`,"title":"T-eval-num2","value_scale":"numeric","max_score":10`)
		ord := file(`,"title":"T-eval-ord2","value_scale":"ordinal"`)
		wantError(t, do(t, h, token, "POST", "/api/v1/assessments/"+num+"/scores", fmt.Sprintf(
			`{"student_id":%q,"level":"A"}`, student)), http.StatusBadRequest, "level_on_numeric")
		wantError(t, do(t, h, token, "POST", "/api/v1/assessments/"+ord+"/scores", fmt.Sprintf(
			`{"student_id":%q,"raw_value":3}`, student)), http.StatusBadRequest, "mark_on_ordinal")
		wantError(t, do(t, h, token, "POST", "/api/v1/assessments/"+num+"/scores", fmt.Sprintf(
			`{"student_id":%q,"raw_value":11}`, student)), http.StatusBadRequest, "mark_out_of_range")
	})

	t.Run("an evidence needs a kind, a criterio and a coherent scale", func(t *testing.T) {
		base := "/api/v1/classes/" + class + "/assessments"
		// Only the two kinds the norm names: a production or a performance.
		for _, kind := range []string{"", "examen", "prueba_escrita"} {
			wantError(t, do(t, h, token, "POST", base, fmt.Sprintf(
				`{"title":"T-eval-x","kind":%q,"term_id":%q,"value_scale":"numeric","max_score":20,"criterion_ids":[%q]}`,
				kind, fx.TermII, fx.CriterionOne)), http.StatusBadRequest, "bad_request")
		}
		wantError(t, do(t, h, token, "POST", base, fmt.Sprintf(
			`{"title":"T-eval-x","kind":"produccion","term_id":%q,"value_scale":"numeric","max_score":20}`, fx.TermII)),
			http.StatusBadRequest, "bad_request")
		wantError(t, do(t, h, token, "POST", base, fmt.Sprintf(
			`{"title":"T-eval-x","kind":"produccion","term_id":%q,"value_scale":"ordinal","max_score":20,"criterion_ids":[%q]}`,
			fx.TermII, fx.CriterionOne)), http.StatusBadRequest, "bad_request")
		wantError(t, do(t, h, token, "POST", base, fmt.Sprintf(
			`{"title":"T-eval-x","kind":"produccion","term_id":%q,"value_scale":"numeric","criterion_ids":[%q]}`,
			fx.TermII, fx.CriterionOne)), http.StatusBadRequest, "bad_request")
	})
}
