package httpapi_test

import (
	"context"
	"fmt"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"

	"github.com/google/uuid"

	"mawta-server/internal/dbtest"
)

// The matrix this file exists for. Every class-scoped route, three callers:
//
//	Quispe  — teaches MAT-5B                  → allowed
//	Rojas   — same school, teaches nothing    → 403 not_assigned_to_class
//	Flores  — another school entirely         → 404 (RLS hid the row first)
//
// Rojas is the case that mattered: before this, "same school" was the only
// check between a teacher and every other teacher's students.
//
// newAPI, login, do, errorCode and the route type come from helpers_test.go.

type caller struct {
	name  string
	token string
}

func callers(t *testing.T, env *dbtest.Env) (quispe, rojas, flores caller) {
	t.Helper()
	return caller{"Quispe (teaches the class)", login(t, env, env.Fx.UserQuispe, env.Fx.TenantA)},
		caller{"Rojas (same school, teaches nothing)", login(t, env, env.Fx.UserRojas, env.Fx.TenantA)},
		caller{"Flores (another school)", login(t, env, env.Fx.UserFlores, env.Fx.TenantB)}
}

func TestClassScopedRoutesRequireAnAssignment(t *testing.T) {
	env := dbtest.Setup(t)
	h := newAPI(t, env)
	quispe, rojas, flores := callers(t, env)

	fx := env.Fx
	class := fx.ClassMat5B.String()
	student := fx.Students[0].String()

	routes := []route{
		{"class dashboard", "GET", "/api/v1/classes/" + class + "/dashboard", ""},
		{"class roster", "GET", "/api/v1/classes/" + class + "/students?competency_id=" + fx.CompetencyC2.String(), ""},
		{"student evidence", "GET", "/api/v1/classes/" + class + "/students/" + student + "/evidence", ""},
		{"student competencies", "GET", "/api/v1/classes/" + class + "/students/" + student + "/competencies", ""},
		{"class criteria", "GET", "/api/v1/classes/" + class + "/criteria", ""},
		{"session header", "GET", "/api/v1/sessions/" + fx.SessionOne.String(), ""},
		{"term plan", "GET", "/api/v1/classes/" + class + "/plan?term_id=" + fx.TermII.String(), ""},
		{"class curriculum", "GET", "/api/v1/classes/" + class + "/curriculum", ""},
		{"class calendar", "GET", "/api/v1/classes/" + class + "/calendar?from=2026-06-01&to=2026-06-30", ""},
	}

	for _, rt := range routes {
		t.Run(rt.name, func(t *testing.T) {
			// The assigned teacher gets through. Any 2xx counts: what is under
			// test is the guard, not each handler's payload.
			if w := do(t, h, quispe.token, rt.method, rt.path, rt.body); w.Code >= 300 {
				t.Errorf("%s: got %d (%s), want a success", quispe.name, w.Code, strings.TrimSpace(w.Body.String()))
			}

			// The colleague down the corridor does not.
			w := do(t, h, rojas.token, rt.method, rt.path, rt.body)
			if w.Code != http.StatusForbidden {
				t.Errorf("%s: got %d, want 403 — this is the gap this guard exists to close", rojas.name, w.Code)
			}
			if code := errorCode(t, w); code != "not_assigned_to_class" {
				t.Errorf("%s: error code = %q, want not_assigned_to_class", rojas.name, code)
			}

			// The other school never learns the row exists.
			if w := do(t, h, flores.token, rt.method, rt.path, rt.body); w.Code != http.StatusNotFound && w.Code != http.StatusForbidden {
				t.Errorf("%s: got %d, want 404 or 403 — never a success", flores.name, w.Code)
			}
		})
	}
}

// The writes, called out separately because a read leaking is bad and a write
// landing in someone else's register is worse.
func TestClassScopedWritesRequireAnAssignment(t *testing.T) {
	env := dbtest.Setup(t)
	h := newAPI(t, env)
	_, rojas, _ := callers(t, env)

	fx := env.Fx
	class := fx.ClassMat5B.String()
	student := fx.Students[0].String()

	routes := []route{
		{"assert an official nivel de logro", "POST",
			"/api/v1/classes/" + class + "/students/" + student + "/competency-levels",
			fmt.Sprintf(`{"competency_id":%q,"level":"C"}`, fx.CompetencyC2)},
		{"write a conclusión descriptiva", "POST",
			"/api/v1/classes/" + class + "/students/" + student + "/conclusions",
			fmt.Sprintf(`{"competency_id":%q,"body":"texto","status":"draft"}`, fx.CompetencyC2)},
		{"create an assessment", "POST", "/api/v1/classes/" + class + "/assessments",
			fmt.Sprintf(`{"title":"Suplantada","value_scale":"numeric","max_score":20,"criterion_ids":[%q]}`, fx.CriterionOne)},
		{"delete someone else's assessment", "POST",
			"/api/v1/assessments/" + fx.AssessmentNumeric.String() + "/delete", ""},
		{"score against someone else's assessment", "POST",
			"/api/v1/assessments/" + fx.AssessmentNumeric.String() + "/scores",
			fmt.Sprintf(`{"student_id":%q,"status":"graded","raw_value":20}`, fx.Students[1])},
		{"correct someone else's score", "POST",
			"/api/v1/scores/" + fx.ScoreOne.String() + "/correct", `{"raw_value":20}`},
		{"start someone else's session", "POST",
			"/api/v1/sessions/" + fx.SessionOne.String() + "/start", ""},
		{"mark a whole roster present", "POST",
			"/api/v1/sessions/" + fx.SessionOne.String() + "/attendance/mark-all-present", ""},
		{"set one student's attendance", "PUT",
			"/api/v1/sessions/" + fx.SessionOne.String() + "/attendance/" + student,
			`{"status":"absent"}`},
		{"create a criterio in another área", "POST",
			"/api/v1/classes/" + class + "/competencies/" + fx.CompetencyC2.String() + "/criteria",
			`{"description":"criterio ajeno","capability_id":"` + fx.CapabilityC2.String() + `"}`},
		{"plan an experience in someone else's class", "POST", "/api/v1/classes/" + class + "/experiences",
			fmt.Sprintf(`{"term_id":%q,"title":"Ajena","idea_text":"idea","starts_on":"2026-06-01","ends_on":"2026-06-12","competency_ids":[%q]}`,
				fx.TermII, fx.CompetencyC1)},
	}

	for _, rt := range routes {
		t.Run(rt.name, func(t *testing.T) {
			w := do(t, h, rojas.token, rt.method, rt.path, rt.body)
			if w.Code != http.StatusForbidden {
				t.Errorf("got %d (%s), want 403", w.Code, strings.TrimSpace(w.Body.String()))
			}
		})
	}
}

// Voice notes are a teacher's own recordings of a child. Another teacher
// should not be able to listen to them, let alone destroy them.
func TestVoiceNoteRoutesRequireAnAssignment(t *testing.T) {
	env := dbtest.Setup(t)
	h := newAPI(t, env)
	_, rojas, _ := callers(t, env)
	ctx := context.Background()

	// Quispe records one. Inserted directly: the HTTP path needs ffmpeg and a
	// real audio blob, and neither is what this test is about.
	voiceNoteID := uuid.New()
	if _, err := env.Admin.Pool.Exec(ctx, `
		insert into voice_notes (id, tenant_id, session_id, student_id, class_id, teacher_id, duration_ms)
		values ($1, $2, $3, $4, $5, $6, 5000)`,
		voiceNoteID, env.Fx.TenantA, env.Fx.SessionOne, env.Fx.Students[0], env.Fx.ClassMat5B, env.Fx.TeacherQuispe); err != nil {
		t.Fatalf("insert a voice note: %v", err)
	}
	t.Cleanup(func() {
		env.Admin.Pool.Exec(ctx, `delete from voice_notes where id = $1`, voiceNoteID) //nolint:errcheck
	})

	for _, rt := range []route{
		{"listen to it", "GET", "/api/v1/voice-notes/" + voiceNoteID.String() + "/audio", ""},
		{"confirm it saved", "POST", "/api/v1/voice-notes/" + voiceNoteID.String() + "/save", ""},
		{"discard it", "POST", "/api/v1/voice-notes/" + voiceNoteID.String() + "/discard", ""},
	} {
		t.Run(rt.name, func(t *testing.T) {
			w := do(t, h, rojas.token, rt.method, rt.path, rt.body)
			if w.Code != http.StatusForbidden {
				t.Errorf("got %d, want 403", w.Code)
			}
		})
	}

	// And it is still there afterwards.
	var deletedAt *string
	if err := env.Admin.Pool.QueryRow(ctx,
		`select deleted_at::text from voice_notes where id = $1`, voiceNoteID).Scan(&deletedAt); err != nil {
		t.Fatalf("read the voice note: %v", err)
	}
	if deletedAt != nil {
		t.Error("a teacher with no assignment discarded another teacher's voice note")
	}
}

// Being assigned to a class is not a licence to name any student id. The
// second axis: the student has to be on that class's roster.
func TestAStudentOutsideTheClassIsRefused(t *testing.T) {
	env := dbtest.Setup(t)
	h := newAPI(t, env)
	quispe, _, _ := callers(t, env)

	// A tenant A student who is on no section of this class.
	outsider := uuid.New()
	ctx := context.Background()
	if _, err := env.Admin.Pool.Exec(ctx, `
		insert into students (id, tenant_id, student_code, given_name, paternal_surname)
		values ($1, $2, 'EST-OUTSIDER', 'Fuera', 'Deaula')`,
		outsider, env.Fx.TenantA); err != nil {
		t.Fatalf("insert an unenrolled student: %v", err)
	}
	t.Cleanup(func() {
		env.Admin.Pool.Exec(ctx, `delete from students where id = $1`, outsider) //nolint:errcheck
	})

	class := env.Fx.ClassMat5B.String()
	for _, rt := range []route{
		{"their evidence", "GET", "/api/v1/classes/" + class + "/students/" + outsider.String() + "/evidence", ""},
		{"their competencies", "GET", "/api/v1/classes/" + class + "/students/" + outsider.String() + "/competencies", ""},
	} {
		t.Run(rt.name, func(t *testing.T) {
			w := do(t, h, quispe.token, rt.method, rt.path, rt.body)
			if w.Code != http.StatusForbidden {
				t.Errorf("got %d, want 403", w.Code)
			}
			if code := errorCode(t, w); code != "student_not_in_class" {
				t.Errorf("error code = %q, want student_not_in_class", code)
			}
		})
	}
}

// The routes whose query key is the teacher were already safe, and must stay
// reachable — guarding them would be a regression, not extra safety.
func TestTeacherKeyedRoutesStayOpen(t *testing.T) {
	env := dbtest.Setup(t)
	h := newAPI(t, env)
	_, rojas, _ := callers(t, env)

	// Rojas teaches nothing at all, which is the strongest case: these must
	// still answer, with his own (empty) data.
	for _, path := range []string{"/api/v1/me", "/api/v1/home", "/api/v1/profile", "/api/v1/notifications"} {
		t.Run(path, func(t *testing.T) {
			if w := do(t, h, rojas.token, "GET", path, ""); w.Code != http.StatusOK {
				t.Errorf("got %d (%s), want 200", w.Code, strings.TrimSpace(w.Body.String()))
			}
		})
	}
}

// No cookie, no access — the guards sit behind sessionAuth and do not replace it.
func TestUnauthenticatedRequestsAreStillRejected(t *testing.T) {
	env := dbtest.Setup(t)
	h := newAPI(t, env)

	r := httptest.NewRequest("GET", "/api/v1/classes/"+env.Fx.ClassMat5B.String()+"/students", nil)
	w := httptest.NewRecorder()
	h.ServeHTTP(w, r)

	if w.Code != http.StatusUnauthorized {
		t.Errorf("got %d, want 401", w.Code)
	}
}

// The planning routes name an experience, a criterion or an evidence as often
// as a class, so each is resolved to its class first. The same three callers,
// on every route of the contract: Rojas and Flores are refused before Quispe
// makes the call succeed, in an order where each write finds what it needs
// (the deletes go last).
func TestPlanningRoutesRequireAnAssignment(t *testing.T) {
	env := dbtest.Setup(t)
	h := newAPI(t, env)
	quispe, rojas, flores := callers(t, env)
	fx := env.Fx

	classID := planClass(t, env)
	class := classID.String()
	exp := createExperience(t, h, quispe.token, env, classID, "2026-06-01", "2026-06-30", fx.CompetencyC1)
	e := "/api/v1/experiences/" + exp.ID.String()
	crit := createCriterion(t, h, quispe.token, exp.ID, fx.CompetencyC1, planPerfC1a, planCapC1a)
	c := "/api/v1/criteria/" + crit.ID.String()
	w := mustDo(t, h, quispe.token, "POST", e+"/evidences",
		fmt.Sprintf(`{"name":"Lista","kind":"produccion","criterion_ids":[%q]}`, crit.ID), http.StatusCreated)
	var ev struct {
		ID uuid.UUID `json:"id"`
	}
	decodeInto(t, w, &ev)
	v := "/api/v1/evidences/" + ev.ID.String()

	routes := []route{
		{"term plan", "GET", "/api/v1/classes/" + class + "/plan?term_id=" + fx.TermII.String(), ""},
		{"class curriculum", "GET", "/api/v1/classes/" + class + "/curriculum", ""},
		{"class calendar", "GET", "/api/v1/classes/" + class + "/calendar?from=2026-06-01&to=2026-06-30", ""},
		{"read an experience", "GET", e, ""},
		{"create an experience", "POST", "/api/v1/classes/" + class + "/experiences",
			experienceBody(env, "2026-07-01", "2026-07-10", fx.CompetencyC1)},
		{"edit an experience", "PUT", e, `{"title":"Editada"}`},
		{"write a criterion", "POST", e + "/criteria", criterionBody(fx.CompetencyC1, planPerfC1b, planCapC1b)},
		{"edit a criterion", "PUT", c, `{"description":"Editado"}`},
		{"accept a criterion", "POST", c + "/accept", ""},
		{"plan an evidence", "POST", e + "/evidences",
			fmt.Sprintf(`{"name":"Otra","kind":"actuacion","criterion_ids":[%q]}`, crit.ID)},
		{"edit an evidence", "PUT", v, `{"name":"Lista editada"}`},
		{"accept an evidence", "POST", v + "/accept", ""},
		{"plan a session", "PUT", e + "/sessions/2026-06-03", `{"title":"Inicio"}`},
		{"accept a session", "POST", e + "/sessions/2026-06-03/accept", ""},
		{"confirm an experience", "POST", e + "/confirm", ""},
		{"delete a session", "POST", e + "/sessions/2026-06-03/delete", ""},
		{"delete an evidence", "POST", v + "/delete", ""},
		{"delete a criterion of an experience", "POST", c + "/delete", ""},
		{"delete an experience", "POST", e + "/delete", ""},
	}

	for _, rt := range routes {
		t.Run(rt.name, func(t *testing.T) {
			w := do(t, h, rojas.token, rt.method, rt.path, rt.body)
			if w.Code != http.StatusForbidden || errorCode(t, w) != "not_assigned_to_class" {
				t.Errorf("%s: got %d %q, want 403 not_assigned_to_class", rojas.name, w.Code, errorCode(t, w))
			}
			if w := do(t, h, flores.token, rt.method, rt.path, rt.body); w.Code != http.StatusNotFound && w.Code != http.StatusForbidden {
				t.Errorf("%s: got %d, want 404 or 403 — never a success", flores.name, w.Code)
			}
			if w := do(t, h, quispe.token, rt.method, rt.path, rt.body); w.Code >= 300 {
				t.Errorf("%s: got %d (%s), want a success", quispe.name, w.Code, strings.TrimSpace(w.Body.String()))
			}
		})
	}
}
