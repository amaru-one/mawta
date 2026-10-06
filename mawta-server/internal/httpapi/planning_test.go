package httpapi_test

import (
	"context"
	"encoding/json"
	"fmt"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"

	"github.com/google/uuid"

	"mawta-server/internal/dbtest"
	"mawta-server/internal/repo"
)

// Tests for the term-planning API (docs/api-planificacion.md).
//
// The HTTP tests commit real rows into one database the whole package shares,
// in random order. Two things follow:
//
//   - Every test that writes plans on a class of its own (planClass), so one
//     test's experiences can never overlap another's, and deletes it after.
//   - What the fixture lacks for planning — the 5S cycle, capabilities and
//     performances, non-teaching days — is added by ensurePlanningCurriculum
//     with fixed ids and "on conflict do nothing", so any test can call it and
//     none of them owns it. fixture.sql stays as it is.

var (
	planCapC1a      = uuid.MustParse("a0000000-0000-4000-8000-000000000402")
	planCapC1b      = uuid.MustParse("a0000000-0000-4000-8000-000000000403")
	planPerfC1a     = uuid.MustParse("a0000000-0000-4000-8000-000000000404")
	planPerfC1b     = uuid.MustParse("a0000000-0000-4000-8000-000000000405")
	planPerfC2      = uuid.MustParse("a0000000-0000-4000-8000-000000000406")
	planPerfC1Of4S  = uuid.MustParse("a0000000-0000-4000-8000-000000000407")
	planGrade4S     = uuid.MustParse("a0000000-0000-4000-8000-000000000401")
	planSubjectCom  = uuid.MustParse("a0000000-0000-4000-8000-000000000408")
	planCompetCom   = uuid.MustParse("a0000000-0000-4000-8000-000000000409")
	planLevelMapID  = uuid.MustParse("a0000000-0000-4000-8000-00000000040a")
	planHoliday     = "2026-06-29"
	planVacationIn  = "2026-07-20"
	planVacationOut = "2026-07-24"
)

// ensurePlanningCurriculum adds the curriculum and calendar planning reads
// on top of the shared fixture. Idempotent.
func ensurePlanningCurriculum(t *testing.T, env *dbtest.Env) {
	t.Helper()
	fx := env.Fx
	adminScript(t, env, "add the planning curriculum", `
		update grade_levels set cycle = 'ciclo_vii' where id = {{grade}} and cycle is null;

		insert into standard_level_mappings (id, tenant_id, modality, cycle, expected_level)
		values ({{mapping}}, {{tenant}}, 'ebr', 'ciclo_vii', 7) on conflict do nothing;

		insert into capabilities (id, tenant_id, competency_id, code, name, sort_order) values
		  ({{capC1a}}, {{tenant}}, {{c1}}, 'MAT-C1-CAP1', 'Traduce cantidades a expresiones numéricas', 1),
		  ({{capC1b}}, {{tenant}}, {{c1}}, 'MAT-C1-CAP2', 'Comunica su comprensión sobre los números y las operaciones', 2)
		on conflict do nothing;

		insert into grade_levels (id, tenant_id, code, label, long_label, ordinal, stage, cycle)
		values ({{grade4S}}, {{tenant}}, '4S', '4to', 'Cuarto de secundaria', 10, 'secundaria', 'ciclo_vii')
		on conflict do nothing;

		insert into grade_level_performances
		  (id, tenant_id, competency_id, grade_level_id, sort_order, official_text, en_proceso,
		   expected_standard_level, suggested_capability_id) values
		  ({{perfC1a}}, {{tenant}}, {{c1}}, {{grade}}, 1, 'Establece relaciones entre datos y acciones de comparar cantidades.', false, 7, {{capC1a}}),
		  ({{perfC1b}}, {{tenant}}, {{c1}}, {{grade}}, 2, 'Expresa con diversas representaciones su comprensión del número.', false, 7, {{capC1b}}),
		  ({{perfC2}}, {{tenant}}, {{c2}}, {{grade}}, 1, 'Establece relaciones entre datos, valores desconocidos y regularidades.', false, 7, null),
		  ({{perf4S}}, {{tenant}}, {{c1}}, {{grade4S}}, 1, 'Desempeño de cuarto grado.', true, 7, null)
		on conflict do nothing;

		insert into subjects (id, tenant_id, code, name)
		values ({{subjectCom}}, {{tenant}}, 'COM', 'Comunicación') on conflict do nothing;
		insert into competencies (id, tenant_id, subject_id, code, name, kind)
		values ({{competCom}}, {{tenant}}, {{subjectCom}}, 'COM-C1', 'Se comunica oralmente en su lengua materna', 'area')
		on conflict do nothing;

		insert into non_teaching_days (tenant_id, academic_year_id, day, kind, label)
		values ({{tenant}}, {{year}}, {{holiday}}, 'feriado', 'San Pedro y San Pablo') on conflict do nothing;
		insert into non_teaching_days (tenant_id, academic_year_id, day, kind, label)
		select {{tenant}}, {{year}}, g.d::date, 'vacaciones', 'Vacaciones de medio año'
		  from generate_series({{vacIn}}::date, {{vacOut}}::date, interval '1 day') as g(d)
		on conflict do nothing;
	`, map[string]any{
		"grade": fx.GradeLevel, "mapping": planLevelMapID, "tenant": fx.TenantA,
		"capC1a": planCapC1a, "capC1b": planCapC1b, "c1": fx.CompetencyC1, "c2": fx.CompetencyC2,
		"grade4S": planGrade4S, "perfC1a": planPerfC1a, "perfC1b": planPerfC1b, "perfC2": planPerfC2,
		"perf4S": planPerfC1Of4S, "subjectCom": planSubjectCom, "competCom": planCompetCom,
		"year": fx.YearA, "holiday": planHoliday, "vacIn": planVacationIn, "vacOut": planVacationOut,
	})
}

// adminScript runs a multi-statement script on the admin pool. Each {{name}}
// becomes vars[name] as a quoted literal; the values are this file's own
// ids and dates, never input. A script with bind parameters could not hold
// more than one statement.
func adminScript(t *testing.T, env *dbtest.Env, what, script string, vars map[string]any) {
	t.Helper()
	pairs := make([]string, 0, 2*len(vars))
	for k, v := range vars {
		pairs = append(pairs, "{{"+k+"}}", "'"+strings.ReplaceAll(fmt.Sprint(v), "'", "''")+"'")
	}
	if _, err := env.Admin.Pool.Exec(context.Background(), strings.NewReplacer(pairs...).Replace(script)); err != nil {
		t.Fatalf("%s: %v", what, err)
	}
}

// planClass creates a Matemática 5to class of its own for Quispe, with a
// Monday/Wednesday timetable over Bimestre II, a double block on 2026-05-20
// and a cancelled session on Friday 2026-05-22, and removes everything
// planned on it when the test ends.
func planClass(t *testing.T, env *dbtest.Env) uuid.UUID {
	t.Helper()
	ensurePlanningCurriculum(t, env)
	ctx := context.Background()
	fx := env.Fx
	sectionID, classID := uuid.New(), uuid.New()
	label := "P" + sectionID.String()[:6]

	adminScript(t, env, "create a planning class", `
		insert into sections (id, tenant_id, academic_year_id, grade_level_id, label, name)
		values ({{section}}, {{tenant}}, {{year}}, {{grade}}, {{label}}, {{label}});
		insert into classes (id, tenant_id, academic_year_id, grade_level_id, course_id, section_id, code, name)
		values ({{class}}, {{tenant}}, {{year}}, {{grade}}, {{course}}, {{section}}, {{label}}, 'Matemática ' || {{label}});
		insert into class_teachers (tenant_id, class_id, teacher_id, role, starts_on)
		values ({{tenant}}, {{class}}, {{teacher}}, 'titular', '2026-03-01');

		insert into class_sessions (tenant_id, academic_year_id, class_id, term_id, session_date,
		                            scheduled_start_at, scheduled_end_at, status)
		select {{tenant}}, {{year}}, {{class}}, {{term}}, g.d::date,
		       (g.d::date + time '08:00') at time zone 'America/Lima',
		       (g.d::date + time '09:30') at time zone 'America/Lima', 'scheduled'
		  from generate_series('2026-05-18'::date, '2026-07-31'::date, interval '1 day') as g(d)
		 where extract(isodow from g.d) in (1, 3);
		insert into class_sessions (tenant_id, academic_year_id, class_id, term_id, session_date,
		                            scheduled_start_at, scheduled_end_at, status)
		values ({{tenant}}, {{year}}, {{class}}, {{term}}, '2026-05-20', '2026-05-20 10:00-05', '2026-05-20 11:00-05', 'scheduled'),
		       ({{tenant}}, {{year}}, {{class}}, {{term}}, '2026-05-22', '2026-05-22 08:00-05', '2026-05-22 09:30-05', 'cancelled');
	`, map[string]any{
		"section": sectionID, "class": classID, "tenant": fx.TenantA, "year": fx.YearA, "grade": fx.GradeLevel,
		"label": label, "course": fx.CourseMat, "teacher": fx.TeacherQuispe, "term": fx.TermII,
	})

	t.Cleanup(func() {
		exp := fmt.Sprintf(`(select id from learning_experiences where class_id = '%s')`, classID)
		_, err := env.Admin.Pool.Exec(ctx, fmt.Sprintf(`
			delete from jobs where kind = 'agent.generate' and payload->>'generation_id' in
			  (select id::text from agent_generations where class_id = '%[2]s');
			delete from agent_generations where class_id = '%[2]s';
			update planned_evidences set session_entry_id = null where experience_id in %[1]s;
			update session_outline_entries set planned_evidence_id = null where experience_id in %[1]s;
			delete from planned_evidence_criteria
			 where evidence_id in (select id from planned_evidences where experience_id in %[1]s);
			delete from evaluation_criterion_capabilities
			 where criterion_id in (select id from evaluation_criteria where experience_id in %[1]s);
			delete from evaluation_criteria where experience_id in %[1]s;
			delete from planned_evidences where experience_id in %[1]s;
			delete from session_outline_entries where experience_id in %[1]s;
			delete from experience_competencies where experience_id in %[1]s;
			delete from learning_experiences where class_id = '%[2]s';
			delete from class_sessions where class_id = '%[2]s';
			delete from class_teachers where class_id = '%[2]s';
			delete from classes where id = '%[2]s';
			delete from sections where id = '%[3]s';
		`, exp, classID, sectionID))
		if err != nil {
			t.Errorf("clean up the planning class: %v", err)
		}
	})
	return classID
}

// expectedClassDates is planClass's timetable seen through the class-date
// rule: Mondays and Wednesdays in [from, to], minus the non-teaching days.
func expectedClassDates(from, to string) []string {
	f, _ := time.Parse("2006-01-02", from)
	l, _ := time.Parse("2006-01-02", to)
	vacFrom, _ := time.Parse("2006-01-02", planVacationIn)
	vacTo, _ := time.Parse("2006-01-02", planVacationOut)
	out := []string{}
	for d := f; !d.After(l); d = d.AddDate(0, 0, 1) {
		if d.Weekday() != time.Monday && d.Weekday() != time.Wednesday {
			continue
		}
		if d.Format("2006-01-02") == planHoliday || (!d.Before(vacFrom) && !d.After(vacTo)) {
			continue
		}
		out = append(out, d.Format("2006-01-02"))
	}
	return out
}

func mustDo(t *testing.T, h http.Handler, token, method, path, body string, want int) *httptest.ResponseRecorder {
	t.Helper()
	w := do(t, h, token, method, path, body)
	if w.Code != want {
		t.Fatalf("%s %s: got %d (%s), want %d", method, path, w.Code, strings.TrimSpace(w.Body.String()), want)
	}
	return w
}

func decodeInto(t *testing.T, w *httptest.ResponseRecorder, v any) {
	t.Helper()
	if err := json.Unmarshal(w.Body.Bytes(), v); err != nil {
		t.Fatalf("decode %s: %v", w.Body.String(), err)
	}
}

// wantError asserts a domain error by status and stable code.
func wantError(t *testing.T, w *httptest.ResponseRecorder, status int, code string) {
	t.Helper()
	if w.Code != status || errorCode(t, w) != code {
		t.Errorf("got %d %q (%s), want %d %q", w.Code, errorCode(t, w), strings.TrimSpace(w.Body.String()), status, code)
	}
}

func experienceBody(env *dbtest.Env, startsOn, endsOn string, competencies ...uuid.UUID) string {
	ids := make([]string, len(competencies))
	for i, c := range competencies {
		ids[i] = fmt.Sprintf("%q", c)
	}
	return fmt.Sprintf(`{"term_id":%q,"title":"La tiendita escolar","idea_text":"Armar una tiendita y calcular vueltos",
		"situation_text":"La I.E. organiza una feria","starts_on":%q,"ends_on":%q,"competency_ids":[%s]}`,
		env.Fx.TermII, startsOn, endsOn, strings.Join(ids, ","))
}

func createExperience(t *testing.T, h http.Handler, token string, env *dbtest.Env, classID uuid.UUID,
	startsOn, endsOn string, competencies ...uuid.UUID) repo.Experience {
	t.Helper()
	w := mustDo(t, h, token, "POST", "/api/v1/classes/"+classID.String()+"/experiences",
		experienceBody(env, startsOn, endsOn, competencies...), http.StatusCreated)
	var e repo.Experience
	decodeInto(t, w, &e)
	return e
}

func createCriterion(t *testing.T, h http.Handler, token string, experienceID, competencyID, performanceID uuid.UUID,
	capabilities ...uuid.UUID) repo.ExperienceCriterion {
	t.Helper()
	w := mustDo(t, h, token, "POST", "/api/v1/experiences/"+experienceID.String()+"/criteria",
		criterionBody(competencyID, performanceID, capabilities...), http.StatusCreated)
	var c repo.ExperienceCriterion
	decodeInto(t, w, &c)
	return c
}

func criterionBody(competencyID, performanceID uuid.UUID, capabilities ...uuid.UUID) string {
	ids := make([]string, len(capabilities))
	for i, c := range capabilities {
		ids[i] = fmt.Sprintf("%q", c)
	}
	return fmt.Sprintf(`{"competency_id":%q,"description":"Calcula el vuelto de una compra","capability_ids":[%s],"performance_id":%q}`,
		competencyID, strings.Join(ids, ","), performanceID)
}

func getExperience(t *testing.T, h http.Handler, token string, id uuid.UUID) repo.Experience {
	t.Helper()
	w := mustDo(t, h, token, "GET", "/api/v1/experiences/"+id.String(), "", http.StatusOK)
	var e repo.Experience
	decodeInto(t, w, &e)
	return e
}

func getPlan(t *testing.T, h http.Handler, token string, classID, termID uuid.UUID) repo.Plan {
	t.Helper()
	w := mustDo(t, h, token, "GET", "/api/v1/classes/"+classID.String()+"/plan?term_id="+termID.String(), "", http.StatusOK)
	var p repo.Plan
	decodeInto(t, w, &p)
	return p
}

func competencyStatus(p repo.Plan, id uuid.UUID) (repo.PlanCompetency, bool) {
	for _, c := range p.Competencies {
		if c.ID == id {
			return c, true
		}
	}
	return repo.PlanCompetency{}, false
}

// ----------------------------------------------------------------- reads --

func TestPlanReadsAnEmptyTerm(t *testing.T) {
	env := dbtest.Setup(t)
	h := newAPI(t, env)
	classID := planClass(t, env)
	token := login(t, env, env.Fx.UserQuispe, env.Fx.TenantA)

	p := getPlan(t, h, token, classID, env.Fx.TermII)
	if p.Term.ID != env.Fx.TermII || p.Term.StartsOn != "2026-05-16" || p.Term.EndsOn != "2026-07-31" {
		t.Errorf("term = %+v, want Bimestre II 2026-05-16..2026-07-31", p.Term)
	}
	// Mondays and Wednesdays, the double block counted once, the cancelled
	// Friday and the non-teaching days left out.
	if want := len(expectedClassDates("2026-05-16", "2026-07-31")); p.ClassDatesTotal != want {
		t.Errorf("class_dates_total = %d, want %d", p.ClassDatesTotal, want)
	}
	wantRanges := []repo.NonTeachingRange{
		{From: planHoliday, To: planHoliday, Kind: "feriado"},
		{From: planVacationIn, To: planVacationOut, Kind: "vacaciones"},
	}
	if len(p.NonTeachingDays) != len(wantRanges) {
		t.Fatalf("non_teaching_days = %+v, want %d ranges", p.NonTeachingDays, len(wantRanges))
	}
	for i, want := range wantRanges {
		got := p.NonTeachingDays[i]
		if got.From != want.From || got.To != want.To || got.Kind != want.Kind || got.Label == nil {
			t.Errorf("non_teaching_days[%d] = %+v, want %s..%s %s with a label", i, got, want.From, want.To, want.Kind)
		}
	}
	if len(p.Experiences) != 0 {
		t.Errorf("experiences = %+v, want none", p.Experiences)
	}

	// Bimestre II is the last term of the fixture's year: with nothing worked,
	// both competencies need two terms and have one left.
	if len(p.Competencies) != 2 {
		t.Fatalf("competencies = %+v, want MAT-C1 and MAT-C2 (never another área's)", p.Competencies)
	}
	for _, c := range p.Competencies {
		if c.Status != "toca" || len(c.TermsWorked) != 0 || c.CapabilitiesCoveredThisTerm != 0 {
			t.Errorf("%s = %+v, want toca, nothing worked", c.Code, c)
		}
	}
	c1, _ := competencyStatus(p, env.Fx.CompetencyC1)
	if c1.CapabilitiesTotal != 2 {
		t.Errorf("MAT-C1 capabilities_total = %d, want 2", c1.CapabilitiesTotal)
	}

	// Without term_id the plan still resolves a term of the class's year.
	w := mustDo(t, h, token, "GET", "/api/v1/classes/"+classID.String()+"/plan", "", http.StatusOK)
	var def repo.Plan
	decodeInto(t, w, &def)
	if def.Term.ID != env.Fx.TermI && def.Term.ID != env.Fx.TermII {
		t.Errorf("default term = %s, want a term of the class's year", def.Term.ID)
	}

	// A term of another school is not found.
	w = do(t, h, token, "GET", "/api/v1/classes/"+classID.String()+"/plan?term_id="+env.Fx.TermB.String(), "")
	wantError(t, w, http.StatusNotFound, "not_found")
}

func TestPlanTracksCompetenciesAcrossTerms(t *testing.T) {
	env := dbtest.Setup(t)
	h := newAPI(t, env)
	classID := planClass(t, env)
	token := login(t, env, env.Fx.UserQuispe, env.Fx.TenantA)

	exp := createExperience(t, h, token, env, classID, "2026-06-01", "2026-06-30", env.Fx.CompetencyC1)
	createCriterion(t, h, token, exp.ID, env.Fx.CompetencyC1, planPerfC1a, planCapC1a)

	p := getPlan(t, h, token, classID, env.Fx.TermII)
	c1, _ := competencyStatus(p, env.Fx.CompetencyC1)
	if c1.Status != "planificada" || len(c1.TermsWorked) != 1 || c1.TermsWorked[0] != 2 || c1.CapabilitiesCoveredThisTerm != 1 {
		t.Errorf("MAT-C1 = %+v, want planificada, worked in term 2, 1 capability covered", c1)
	}
	c2, _ := competencyStatus(p, env.Fx.CompetencyC2)
	if c2.Status != "toca" {
		t.Errorf("MAT-C2 = %+v, want toca", c2)
	}
	if len(p.Experiences) != 1 {
		t.Fatalf("experiences = %+v, want one", p.Experiences)
	}
	e := p.Experiences[0]
	if e.ID != exp.ID || e.Status != "borrador" || e.ClassDates != len(expectedClassDates("2026-06-01", "2026-06-30")) ||
		len(e.Competencies) != 1 || e.Competencies[0].CapabilitiesTotal != 2 || e.Competencies[0].CapabilitiesWithCriteria != 1 ||
		e.PendingProposals != 0 {
		t.Errorf("experience = %+v", e)
	}

	// Seen from Bimestre I, MAT-C1 is worked once (in II) and two terms remain:
	// it can wait. MAT-C2 still needs both remaining terms: it is due.
	p = getPlan(t, h, token, classID, env.Fx.TermI)
	c1, _ = competencyStatus(p, env.Fx.CompetencyC1)
	if c1.Status != "puede_esperar" {
		t.Errorf("MAT-C1 from Bimestre I = %+v, want puede_esperar", c1)
	}
	c2, _ = competencyStatus(p, env.Fx.CompetencyC2)
	if c2.Status != "toca" {
		t.Errorf("MAT-C2 from Bimestre I = %+v, want toca", c2)
	}
}

func TestCurriculumOfTheClassGrade(t *testing.T) {
	env := dbtest.Setup(t)
	h := newAPI(t, env)
	classID := planClass(t, env)
	token := login(t, env, env.Fx.UserQuispe, env.Fx.TenantA)

	w := mustDo(t, h, token, "GET", "/api/v1/classes/"+classID.String()+"/curriculum", "", http.StatusOK)
	var c repo.Curriculum
	decodeInto(t, w, &c)
	if c.Grade.Code != "5S" || c.Grade.Cycle == nil || *c.Grade.Cycle != "ciclo_vii" ||
		c.Grade.ExpectedLevel == nil || *c.Grade.ExpectedLevel != 7 {
		t.Errorf("grade = %+v, want 5S, ciclo_vii, level 7", c.Grade)
	}
	if len(c.Competencies) != 2 {
		t.Fatalf("competencies = %+v, want the two of Matemática", c.Competencies)
	}
	for _, comp := range c.Competencies {
		switch comp.ID {
		case env.Fx.CompetencyC1:
			if len(comp.Capabilities) != 2 || len(comp.Performances) != 2 {
				t.Errorf("MAT-C1 = %+v, want 2 capabilities and the 2 performances of 5S (not 4S's)", comp)
			}
			if p := comp.Performances[0]; p.ID != planPerfC1a || p.Order != 1 || p.SuggestedCapabilityID == nil ||
				*p.SuggestedCapabilityID != planCapC1a || p.Text == "" {
				t.Errorf("MAT-C1 first performance = %+v", p)
			}
		case env.Fx.CompetencyC2:
			if len(comp.Capabilities) != 1 || len(comp.Performances) != 1 {
				t.Errorf("MAT-C2 = %+v, want 1 capability and 1 performance", comp)
			}
		default:
			t.Errorf("unexpected competency %s", comp.Code)
		}
	}
}

func TestCalendarOfAClass(t *testing.T) {
	env := dbtest.Setup(t)
	h := newAPI(t, env)
	classID := planClass(t, env)
	token := login(t, env, env.Fx.UserQuispe, env.Fx.TenantA)
	base := "/api/v1/classes/" + classID.String() + "/calendar"

	w := mustDo(t, h, token, "GET", base+"?from=2026-05-18&to=2026-07-31", "", http.StatusOK)
	var cal repo.Calendar
	decodeInto(t, w, &cal)
	want := expectedClassDates("2026-05-18", "2026-07-31")
	if strings.Join(cal.ClassDates, ",") != strings.Join(want, ",") {
		t.Errorf("class_dates = %v, want %v", cal.ClassDates, want)
	}
	if len(cal.NonTeachingDays) != 6 || cal.NonTeachingDays[0].Date != planHoliday || cal.NonTeachingDays[0].Kind != "feriado" {
		t.Errorf("non_teaching_days = %+v, want the holiday and the five vacation days", cal.NonTeachingDays)
	}

	for _, q := range []string{
		"?from=2026-03-01&to=2026-12-01", // longer than any term
		"?from=2026-06-10&to=2026-06-01", // backwards
		"?from=junio&to=2026-06-30",      // not a date
		"",                               // missing
	} {
		wantError(t, do(t, h, token, "GET", base+q, ""), http.StatusBadRequest, "bad_request")
	}
}

// ---------------------------------------------------------------- writes --

// TestPlanningAnExperience walks the whole flow: draft, criteria, evidences,
// sessions, proposals, confirm, then taking it apart again.
func TestPlanningAnExperience(t *testing.T) {
	env := dbtest.Setup(t)
	h := newAPI(t, env)
	classID := planClass(t, env)
	token := login(t, env, env.Fx.UserQuispe, env.Fx.TenantA)
	ctx := context.Background()
	fx := env.Fx

	exp := createExperience(t, h, token, env, classID, "2026-06-01", "2026-06-30", fx.CompetencyC1, fx.CompetencyC2)
	if exp.Status != "borrador" || exp.ClassID != classID || exp.TermID != fx.TermII || len(exp.Competencies) != 2 ||
		exp.SituationText == nil || exp.IdeaText == "" {
		t.Errorf("created experience = %+v", exp)
	}
	if want := expectedClassDates("2026-06-01", "2026-06-30"); strings.Join(exp.ClassDates, ",") != strings.Join(want, ",") {
		t.Errorf("class_dates = %v, want %v", exp.ClassDates, want)
	}
	// Three capabilities, no criteria: three warnings, nothing pending.
	if len(exp.Warnings) != 3 {
		t.Errorf("warnings = %+v, want one capability_without_criterion per capability", exp.Warnings)
	}
	expPath := "/api/v1/experiences/" + exp.ID.String()

	// A criterion looking at both capabilities of MAT-C1.
	crit := createCriterion(t, h, token, exp.ID, fx.CompetencyC1, planPerfC1a, planCapC1a, planCapC1b)
	if crit.ProposedBy != "teacher" || crit.AcceptedAt == nil || len(crit.CapabilityIDs) != 2 ||
		crit.PerformanceID == nil || *crit.PerformanceID != planPerfC1a || crit.ExperienceID != exp.ID {
		t.Errorf("criterion = %+v", crit)
	}

	// Edit it down to one capability and another performance.
	w := mustDo(t, h, token, "PUT", "/api/v1/criteria/"+crit.ID.String(), fmt.Sprintf(
		`{"description":"Calcula el vuelto exacto","capability_ids":[%q],"performance_id":%q}`, planCapC1b, planPerfC1b), http.StatusOK)
	decodeInto(t, w, &crit)
	if crit.Description != "Calcula el vuelto exacto" || len(crit.CapabilityIDs) != 1 || crit.CapabilityIDs[0] != planCapC1b ||
		*crit.PerformanceID != planPerfC1b {
		t.Errorf("edited criterion = %+v", crit)
	}

	// A planned evidence over it, not placed yet.
	w = mustDo(t, h, token, "POST", expPath+"/evidences", fmt.Sprintf(
		`{"name":"Lista de precios","kind":"produccion","criterion_ids":[%q]}`, crit.ID), http.StatusCreated)
	var ev repo.ExperienceEvidence
	decodeInto(t, w, &ev)
	if ev.SessionDate != nil || len(ev.CriterionIDs) != 1 || ev.ProposedBy != "teacher" || ev.AcceptedAt == nil {
		t.Errorf("evidence = %+v", ev)
	}

	// A session on 2026-06-03 that collects it: both sides of the placement move.
	w = mustDo(t, h, token, "PUT", expPath+"/sessions/2026-06-03", fmt.Sprintf(
		`{"title":"¿Qué vendemos?","topics":"Precios y vueltos","planned_evidence_id":%q}`, ev.ID), http.StatusOK)
	var ses repo.ExperienceSession
	decodeInto(t, w, &ses)
	if ses.Date != "2026-06-03" || ses.PlannedEvidenceID == nil || *ses.PlannedEvidenceID != ev.ID || ses.AcceptedAt == nil {
		t.Errorf("session = %+v", ses)
	}
	assertPlacement(t, env, ev.ID, "2026-06-03")

	// Unplace it from the evidence side, then place it again.
	w = mustDo(t, h, token, "PUT", "/api/v1/evidences/"+ev.ID.String(), `{"session_date":null}`, http.StatusOK)
	decodeInto(t, w, &ev)
	if ev.SessionDate != nil {
		t.Errorf("evidence after session_date null = %+v", ev)
	}
	assertPlacement(t, env, ev.ID, "")
	mustDo(t, h, token, "PUT", "/api/v1/evidences/"+ev.ID.String(), `{"session_date":"2026-06-03","name":"Lista de precios final"}`, http.StatusOK)
	assertPlacement(t, env, ev.ID, "2026-06-03")

	// Leaving session_date out keeps the placement.
	mustDo(t, h, token, "PUT", "/api/v1/evidences/"+ev.ID.String(), `{"kind":"actuacion"}`, http.StatusOK)
	assertPlacement(t, env, ev.ID, "2026-06-03")

	// A second session; replacing the first without an evidence empties it.
	mustDo(t, h, token, "PUT", expPath+"/sessions/2026-06-08", `{"title":"Armamos la tiendita"}`, http.StatusOK)
	mustDo(t, h, token, "PUT", expPath+"/sessions/2026-06-03", `{"title":"¿Qué vendemos? (v2)"}`, http.StatusOK)
	assertPlacement(t, env, ev.ID, "")
	mustDo(t, h, token, "PUT", expPath+"/sessions/2026-06-03",
		fmt.Sprintf(`{"title":"¿Qué vendemos?","planned_evidence_id":%q}`, ev.ID), http.StatusOK)
	// Moving the evidence to another session empties the first one.
	mustDo(t, h, token, "PUT", expPath+"/sessions/2026-06-08",
		fmt.Sprintf(`{"title":"Armamos la tiendita","planned_evidence_id":%q}`, ev.ID), http.StatusOK)
	assertPlacement(t, env, ev.ID, "2026-06-08")

	// Mawta's proposals, as the planning agent will write them: pending until
	// the teacher accepts or edits them.
	// The criterion and its capability go in one transaction, as the
	// deferred check_criterion_on_write requires.
	propCrit, propEv := uuid.New(), uuid.New()
	adminScript(t, env, "insert a proposed criterion", `
		begin;
		insert into evaluation_criteria (id, tenant_id, competency_id, description, experience_id, performance_id, proposed_by)
		values ({{id}}, {{tenant}}, {{c2}}, 'Propuesta de Mawta', {{exp}}, {{perf}}, 'mawta');
		insert into evaluation_criterion_capabilities (tenant_id, criterion_id, competency_id, capability_id)
		values ({{tenant}}, {{id}}, {{c2}}, {{cap}});
		commit;
	`, map[string]any{"id": propCrit, "tenant": fx.TenantA, "c2": fx.CompetencyC2, "exp": exp.ID,
		"perf": planPerfC2, "cap": fx.CapabilityC2})
	if err := env.Admin.Pool.QueryRow(ctx, `
		insert into planned_evidences (id, tenant_id, experience_id, name, kind, proposed_by)
		values ($1, $2, $3, 'Exposición propuesta', 'actuacion', 'mawta') returning id
	`, propEv, fx.TenantA, exp.ID).Scan(&propEv); err != nil {
		t.Fatalf("insert a proposed evidence: %v", err)
	}
	if _, err := env.Admin.Pool.Exec(ctx, `
		insert into session_outline_entries (tenant_id, experience_id, class_date, title, proposed_by)
		values ($1, $2, '2026-06-10', 'Sesión propuesta', 'mawta')
	`, fx.TenantA, exp.ID); err != nil {
		t.Fatalf("insert a proposed session: %v", err)
	}

	got := getExperience(t, h, token, exp.ID)
	if pending := findWarning(got.Warnings, "pending_proposals"); pending == nil || pending.Count == nil || *pending.Count != 3 {
		t.Errorf("warnings = %+v, want pending_proposals 3", got.Warnings)
	}
	// A pending proposal does not cover its capability.
	if findWarning(got.Warnings, "capability_without_criterion") == nil {
		t.Errorf("warnings = %+v, want MAT-C2's capability still uncovered while its criterion is pending", got.Warnings)
	}
	if p := getPlan(t, h, token, classID, fx.TermII); len(p.Experiences) != 1 || p.Experiences[0].PendingProposals != 3 {
		t.Errorf("plan experiences = %+v, want pending_proposals 3", p.Experiences)
	}

	// Editing a proposal accepts it; accept takes one as it is.
	w = mustDo(t, h, token, "PUT", "/api/v1/criteria/"+propCrit.String(), `{"description":"Propuesta editada"}`, http.StatusOK)
	var pc repo.ExperienceCriterion
	decodeInto(t, w, &pc)
	if pc.ProposedBy != "mawta" || pc.AcceptedAt == nil || pc.Description != "Propuesta editada" {
		t.Errorf("edited proposal = %+v, want mawta, accepted", pc)
	}
	w = mustDo(t, h, token, "POST", "/api/v1/evidences/"+propEv.String()+"/accept", "", http.StatusOK)
	var pe repo.ExperienceEvidence
	decodeInto(t, w, &pe)
	if pe.AcceptedAt == nil || pe.Name != "Exposición propuesta" {
		t.Errorf("accepted evidence = %+v", pe)
	}
	w = mustDo(t, h, token, "POST", expPath+"/sessions/2026-06-10/accept", "", http.StatusOK)
	decodeInto(t, w, &ses)
	if ses.AcceptedAt == nil || ses.ProposedBy != "mawta" {
		t.Errorf("accepted session = %+v", ses)
	}
	mustDo(t, h, token, "POST", "/api/v1/criteria/"+propCrit.String()+"/accept", "", http.StatusOK) // already accepted: no-op

	// Every capability now has an accepted criterion except MAT-C1-CAP1
	// (the first criterion was edited down to CAP2).
	got = getExperience(t, h, token, exp.ID)
	if len(got.Warnings) != 1 || got.Warnings[0].Code != "capability_without_criterion" ||
		*got.Warnings[0].CapabilityID != planCapC1a {
		t.Errorf("warnings = %+v, want only MAT-C1-CAP1 uncovered", got.Warnings)
	}

	// Edit the experience itself.
	w = mustDo(t, h, token, "PUT", expPath, `{"title":"La tiendita","situation_text":"","ends_on":"2026-06-24"}`, http.StatusOK)
	decodeInto(t, w, &got)
	if got.Title != "La tiendita" || got.SituationText != nil || got.EndsOn != "2026-06-24" {
		t.Errorf("edited experience = %+v", got)
	}

	// Confirm.
	w = mustDo(t, h, token, "POST", expPath+"/confirm", "", http.StatusOK)
	decodeInto(t, w, &got)
	if got.Status != "planificada" || len(got.Warnings) != 1 {
		t.Errorf("confirmed experience = %+v, want planificada with its warning", got)
	}

	// Deleting a criterion takes it out of the evidences that observe it.
	mustDo(t, h, token, "POST", "/api/v1/criteria/"+crit.ID.String()+"/delete", "", http.StatusNoContent)
	got = getExperience(t, h, token, exp.ID)
	for _, e := range got.Evidences {
		for _, c := range e.CriterionIDs {
			if c == crit.ID {
				t.Errorf("evidence %s still observes the deleted criterion", e.ID)
			}
		}
	}

	// Deleting a session leaves its evidence unplaced; deleting an evidence
	// empties its session.
	mustDo(t, h, token, "POST", expPath+"/sessions/2026-06-08/delete", "", http.StatusNoContent)
	assertPlacement(t, env, ev.ID, "")
	mustDo(t, h, token, "PUT", expPath+"/sessions/2026-06-03",
		fmt.Sprintf(`{"title":"¿Qué vendemos?","planned_evidence_id":%q}`, ev.ID), http.StatusOK)
	mustDo(t, h, token, "POST", "/api/v1/evidences/"+ev.ID.String()+"/delete", "", http.StatusNoContent)
	got = getExperience(t, h, token, exp.ID)
	for _, s := range got.Sessions {
		if s.PlannedEvidenceID != nil && *s.PlannedEvidenceID == ev.ID {
			t.Errorf("session %s still points at the deleted evidence", s.Date)
		}
	}
	wantError(t, do(t, h, token, "POST", expPath+"/sessions/2026-06-08/delete", ""), http.StatusNotFound, "not_found")
	wantError(t, do(t, h, token, "POST", "/api/v1/evidences/"+ev.ID.String()+"/accept", ""), http.StatusNotFound, "not_found")

	// Deleting the experience takes everything with it and frees its dates.
	mustDo(t, h, token, "POST", expPath+"/delete", "", http.StatusNoContent)
	wantError(t, do(t, h, token, "GET", expPath, ""), http.StatusNotFound, "not_found")
	var live int
	if err := env.Admin.Pool.QueryRow(ctx, `
		select (select count(*) from evaluation_criteria where experience_id = $1 and deleted_at is null)
		     + (select count(*) from planned_evidences where experience_id = $1 and deleted_at is null)
		     + (select count(*) from session_outline_entries where experience_id = $1 and deleted_at is null)
		     + (select count(*) from experience_competencies where experience_id = $1 and deleted_at is null)
	`, exp.ID).Scan(&live); err != nil {
		t.Fatal(err)
	}
	if live != 0 {
		t.Errorf("%d rows of the deleted experience are still live", live)
	}
	if p := getPlan(t, h, token, classID, fx.TermII); len(p.Experiences) != 0 {
		t.Errorf("plan still lists %+v", p.Experiences)
	}
	createExperience(t, h, token, env, classID, "2026-06-01", "2026-06-30", fx.CompetencyC1)
}

func findWarning(ws []repo.Warning, code string) *repo.Warning {
	for i := range ws {
		if ws[i].Code == code {
			return &ws[i]
		}
	}
	return nil
}

// assertPlacement checks both sides of an evidence's placement agree: date
// "" means unplaced.
func assertPlacement(t *testing.T, env *dbtest.Env, evidenceID uuid.UUID, date string) {
	t.Helper()
	var fromEvidence, fromEntries *string
	var entries int
	if err := env.Admin.Pool.QueryRow(context.Background(), `
		select (select to_char(se.class_date, 'YYYY-MM-DD')
		          from planned_evidences pe
		          join session_outline_entries se on se.id = pe.session_entry_id and se.deleted_at is null
		         where pe.id = $1),
		       (select string_agg(to_char(class_date, 'YYYY-MM-DD'), ',')
		          from session_outline_entries where planned_evidence_id = $1 and deleted_at is null),
		       (select count(*) from session_outline_entries where planned_evidence_id = $1 and deleted_at is null)
	`, evidenceID).Scan(&fromEvidence, &fromEntries, &entries); err != nil {
		t.Fatalf("read the placement: %v", err)
	}
	str := func(s *string) string {
		if s == nil {
			return ""
		}
		return *s
	}
	if str(fromEvidence) != date || str(fromEntries) != date || (date != "" && entries != 1) {
		t.Errorf("placement: evidence says %q, sessions say %q; want %q on both sides", str(fromEvidence), str(fromEntries), date)
	}
}

// TestPlanningDomainErrors provokes each stable code of the contract's
// "Domain errors" table (generation_failed belongs to ticket 6).
func TestPlanningDomainErrors(t *testing.T) {
	env := dbtest.Setup(t)
	h := newAPI(t, env)
	classID := planClass(t, env)
	token := login(t, env, env.Fx.UserQuispe, env.Fx.TenantA)
	fx := env.Fx
	classPath := "/api/v1/classes/" + classID.String() + "/experiences"

	a := createExperience(t, h, token, env, classID, "2026-06-01", "2026-06-12", fx.CompetencyC1)
	b := createExperience(t, h, token, env, classID, "2026-06-15", "2026-06-30", fx.CompetencyC1, fx.CompetencyC2)
	aPath := "/api/v1/experiences/" + a.ID.String()
	bPath := "/api/v1/experiences/" + b.ID.String()
	critA := createCriterion(t, h, token, a.ID, fx.CompetencyC1, planPerfC1a, planCapC1a)
	mustDo(t, h, token, "PUT", aPath+"/sessions/2026-06-03", `{"title":"Inicio"}`, http.StatusOK)
	w := mustDo(t, h, token, "POST", bPath+"/evidences", fmt.Sprintf(
		`{"name":"Otra","kind":"prueba_escrita","criterion_ids":[%q]}`,
		createCriterion(t, h, token, b.ID, fx.CompetencyC2, planPerfC2, fx.CapabilityC2).ID), http.StatusCreated)
	var evB repo.ExperienceEvidence
	decodeInto(t, w, &evB)

	cases := []struct {
		name         string
		method, path string
		body         string
		status       int
		code         string
	}{
		{"overlapping dates", "POST", classPath, experienceBody(env, "2026-06-10", "2026-06-20", fx.CompetencyC1),
			http.StatusConflict, "experience_overlap"},
		{"moving into another experience", "PUT", aPath, `{"ends_on":"2026-06-16"}`,
			http.StatusConflict, "experience_overlap"},
		{"ending after the term", "POST", classPath, experienceBody(env, "2026-07-27", "2026-08-07", fx.CompetencyC1),
			http.StatusUnprocessableEntity, "outside_term"},
		{"starting before the term", "PUT", aPath, `{"starts_on":"2026-05-10"}`,
			http.StatusUnprocessableEntity, "outside_term"},
		{"another área's competency", "POST", classPath, experienceBody(env, "2026-07-01", "2026-07-10", planCompetCom),
			http.StatusUnprocessableEntity, "competency_not_in_subject"},
		{"adding another área's competency", "PUT", aPath, fmt.Sprintf(`{"competency_ids":[%q,%q]}`, fx.CompetencyC1, planCompetCom),
			http.StatusUnprocessableEntity, "competency_not_in_subject"},
		{"removing a competency with criteria", "PUT", aPath, fmt.Sprintf(`{"competency_ids":[%q]}`, fx.CompetencyC2),
			http.StatusConflict, "competency_has_criteria"},
		{"a capability of another competency", "POST", aPath + "/criteria", criterionBody(fx.CompetencyC1, planPerfC1a, fx.CapabilityC2),
			http.StatusUnprocessableEntity, "capability_not_in_competency"},
		{"editing to a capability of another competency", "PUT", "/api/v1/criteria/" + critA.ID.String(),
			fmt.Sprintf(`{"capability_ids":[%q]}`, fx.CapabilityC2), http.StatusUnprocessableEntity, "capability_not_in_competency"},
		{"a criterion without capabilities", "POST", aPath + "/criteria", criterionBody(fx.CompetencyC1, planPerfC1a),
			http.StatusUnprocessableEntity, "criterion_needs_capability"},
		{"editing away every capability", "PUT", "/api/v1/criteria/" + critA.ID.String(), `{"capability_ids":[]}`,
			http.StatusUnprocessableEntity, "criterion_needs_capability"},
		{"a performance of another grade", "POST", aPath + "/criteria", criterionBody(fx.CompetencyC1, planPerfC1Of4S, planCapC1a),
			http.StatusUnprocessableEntity, "performance_not_in_grade"},
		{"a performance of another competency", "PUT", "/api/v1/criteria/" + critA.ID.String(),
			fmt.Sprintf(`{"performance_id":%q}`, planPerfC2), http.StatusUnprocessableEntity, "performance_not_in_grade"},
		{"a competency the experience does not work", "POST", aPath + "/criteria", criterionBody(fx.CompetencyC2, planPerfC2, fx.CapabilityC2),
			http.StatusUnprocessableEntity, "competency_not_in_experience"},
		{"a criterion of another área's competency", "POST", aPath + "/criteria", criterionBody(planCompetCom, planPerfC2, fx.CapabilityC2),
			http.StatusUnprocessableEntity, "competency_not_in_subject"},
		{"an evidence over another experience's criterion", "POST", bPath + "/evidences",
			fmt.Sprintf(`{"name":"Cruzada","kind":"produccion","criterion_ids":[%q]}`, critA.ID),
			http.StatusUnprocessableEntity, "criterion_other_experience"},
		{"re-pointing an evidence at another experience's criterion", "PUT", "/api/v1/evidences/" + evB.ID.String(),
			fmt.Sprintf(`{"criterion_ids":[%q]}`, critA.ID), http.StatusUnprocessableEntity, "criterion_other_experience"},
		{"an evidence in a date without a session", "POST", aPath + "/evidences",
			fmt.Sprintf(`{"name":"Sin sesión","kind":"produccion","criterion_ids":[%q],"session_date":"2026-06-08"}`, critA.ID),
			http.StatusUnprocessableEntity, "date_not_in_experience"},
		{"moving an evidence to a date without a session", "PUT", "/api/v1/evidences/" + evB.ID.String(),
			`{"session_date":"2026-06-17"}`, http.StatusUnprocessableEntity, "date_not_in_experience"},
		{"a session on a holiday", "PUT", bPath + "/sessions/" + planHoliday, `{"title":"Feriado"}`,
			http.StatusUnprocessableEntity, "date_not_in_experience"},
		{"a session on a day without class", "PUT", aPath + "/sessions/2026-06-02", `{"title":"Martes"}`,
			http.StatusUnprocessableEntity, "date_not_in_experience"},
		{"a session outside the experience", "PUT", aPath + "/sessions/2026-06-15", `{"title":"De la otra"}`,
			http.StatusUnprocessableEntity, "date_not_in_experience"},
		{"shrinking the dates past a session", "PUT", aPath, `{"starts_on":"2026-06-08"}`,
			http.StatusUnprocessableEntity, "date_not_in_experience"},
		{"a session holding another experience's evidence", "PUT", aPath + "/sessions/2026-06-03",
			fmt.Sprintf(`{"title":"Inicio","planned_evidence_id":%q}`, evB.ID), http.StatusUnprocessableEntity, "evidence_not_in_experience"},
		{"a criterion without a description", "POST", aPath + "/criteria",
			fmt.Sprintf(`{"competency_id":%q,"description":"  ","capability_ids":[%q],"performance_id":%q}`, fx.CompetencyC1, planCapC1a, planPerfC1a),
			http.StatusBadRequest, "missing_description"},
		{"an experience without competencies", "POST", classPath, experienceBody(env, "2026-07-01", "2026-07-10"),
			http.StatusBadRequest, "missing_competencies"},
		{"an evidence of an unknown kind", "POST", aPath + "/evidences",
			fmt.Sprintf(`{"name":"Rara","kind":"examen","criterion_ids":[%q]}`, critA.ID), http.StatusBadRequest, "bad_request"},
		{"an evidence without criteria", "POST", aPath + "/evidences", `{"name":"Sola","kind":"produccion","criterion_ids":[]}`,
			http.StatusBadRequest, "missing_criteria"},
		{"a term of another year", "POST", classPath, strings.Replace(experienceBody(env, "2026-07-01", "2026-07-10", fx.CompetencyC1),
			fx.TermII.String(), fx.TermB.String(), 1), http.StatusNotFound, "not_found"},
		{"a global criterion through the planning routes", "PUT", "/api/v1/criteria/" + fx.CriterionOne.String(),
			`{"description":"x"}`, http.StatusNotFound, "not_found"},
		{"accepting a session that does not exist", "POST", aPath + "/sessions/2026-06-10/accept", "",
			http.StatusNotFound, "not_found"},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			wantError(t, do(t, h, token, tc.method, tc.path, tc.body), tc.status, tc.code)
		})
	}

	// Confirming twice.
	mustDo(t, h, token, "POST", aPath+"/confirm", "", http.StatusOK)
	wantError(t, do(t, h, token, "POST", aPath+"/confirm", ""), http.StatusConflict, "experience_not_draft")

	// Nothing above changed experience A behind the rejections.
	got := getExperience(t, h, token, a.ID)
	if got.StartsOn != "2026-06-01" || got.EndsOn != "2026-06-12" || len(got.Competencies) != 1 ||
		len(got.Criteria) != 1 || len(got.Criteria[0].CapabilityIDs) != 1 || len(got.Sessions) != 1 {
		t.Errorf("experience A after the rejections = %+v", got)
	}
}
