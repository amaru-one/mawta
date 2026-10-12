package httpapi_test

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"log/slog"
	"net/http"
	"strings"
	"testing"

	"github.com/google/uuid"

	"mawta-server/internal/agent"
	"mawta-server/internal/agent/llm"
	"mawta-server/internal/agent/planning"
	"mawta-server/internal/config"
	"mawta-server/internal/dbtest"
	"mawta-server/internal/repo"
)

// Tests for "✦ Generar con Mawta" (docs/api-planificacion.md, "Generate with
// Mawta"). A route records a generation and queues its job; the test then
// runs the job's work the way the worker does — agent.Runner.Run — over a
// scripted model, and reads the outcome back through the API.

func withAgent(cfg *config.Config) { cfg.AnthropicAPIKey = "test-key" }

type generation struct {
	ID     uuid.UUID       `json:"id"`
	Kind   string          `json:"kind"`
	Status string          `json:"status"`
	Result json.RawMessage `json:"result"`
	Error  *string         `json:"error"`
}

func requestGeneration(t *testing.T, h http.Handler, token, path, body string) generation {
	t.Helper()
	w := mustDo(t, h, token, "POST", path, body, http.StatusAccepted)
	var g generation
	decodeInto(t, w, &g)
	if g.Status != "pending" {
		t.Fatalf("a new generation is pending, got %q", g.Status)
	}
	return g
}

func getGeneration(t *testing.T, h http.Handler, token string, id uuid.UUID) generation {
	t.Helper()
	w := mustDo(t, h, token, "GET", "/api/v1/generations/"+id.String(), "", http.StatusOK)
	var g generation
	decodeInto(t, w, &g)
	return g
}

func newRunner(env *dbtest.Env, model llm.Model) *agent.Runner {
	prices := llm.Prices{InputPerMTok: 3, OutputPerMTok: 15}
	return agent.NewRunner(env.App, model, prices, slog.New(slog.NewTextHandler(io.Discard, nil)), planning.New())
}

// runJob runs one attempt of a generation's job, as the worker would.
func runJob(t *testing.T, env *dbtest.Env, r *agent.Runner, id uuid.UUID, attempt, maxAttempts int16) (agent.Outcome, error) {
	t.Helper()
	payload, _ := json.Marshal(agent.JobPayload{GenerationID: id})
	return r.Run(context.Background(), env.Fx.TenantA, payload, attempt, maxAttempts)
}

func mustRun(t *testing.T, env *dbtest.Env, r *agent.Runner, id uuid.UUID) {
	t.Helper()
	outcome, err := runJob(t, env, r, id, 1, agent.MaxAttempts)
	if err != nil || outcome != agent.OutcomeCompleted {
		t.Fatalf("run generation: outcome %q, err %v", outcome, err)
	}
}

func reply(v any) llm.FakeReply {
	b, _ := json.Marshal(v)
	return llm.FakeReply{Input: string(b), Usage: llm.Usage{InputTokens: 1200, OutputTokens: 300}}
}

func TestGenerationRoutesNeedTheAgent(t *testing.T) {
	env := dbtest.Setup(t)
	h := newAPI(t, env) // no ANTHROPIC_API_KEY
	quispe, _, _ := callers(t, env)
	classID := planClass(t, env)
	exp := createExperience(t, h, quispe.token, env, classID, "2026-05-18", "2026-05-29", env.Fx.CompetencyC1)

	for _, path := range []string{
		"/api/v1/classes/" + classID.String() + "/experience-proposals",
		"/api/v1/experiences/" + exp.ID.String() + "/criteria/generate",
		"/api/v1/experiences/" + exp.ID.String() + "/evidences/generate",
		"/api/v1/experiences/" + exp.ID.String() + "/sessions/generate",
	} {
		body := fmt.Sprintf(`{"term_id":%q,"idea_text":"una feria","competency_id":%q}`, env.Fx.TermII, env.Fx.CompetencyC1)
		wantError(t, do(t, h, quispe.token, "POST", path, body), http.StatusServiceUnavailable, "agent_unavailable")
	}
}

func TestExperienceProposalFromAnIdea(t *testing.T) {
	env := dbtest.Setup(t)
	h := newAPI(t, env, withAgent)
	quispe, _, _ := callers(t, env)
	classID := planClass(t, env)
	fx := env.Fx
	createExperience(t, h, quispe.token, env, classID, "2026-06-01", "2026-06-12", fx.CompetencyC1)

	path := "/api/v1/classes/" + classID.String() + "/experience-proposals"
	body := fmt.Sprintf(`{"term_id":%q,"idea_text":"Una feria de emprendimiento donde calculen precios y ganancias","competency_ids":[%q]}`,
		fx.TermII, fx.CompetencyC1)
	g := requestGeneration(t, h, quispe.token, path, body)
	if again := requestGeneration(t, h, quispe.token, path, body); again.ID != g.ID {
		t.Errorf("a second request while one is pending returns it: got %s, want %s", again.ID, g.ID)
	}

	// The model picks another competency (the teacher's choice wins) and
	// dates that cross the existing experience (the server moves them).
	model := &llm.Fake{Replies: []llm.FakeReply{reply(map[string]any{
		"title":          "Feria de emprendimiento",
		"situation_text": "La I.E. organiza una feria. ¿Cómo fijamos precios justos y calculamos ganancias?",
		"competency_ids": []string{fx.CompetencyC2.String()},
		"starts_on":      "2026-06-08",
		"ends_on":        "2026-06-19",
	})}}
	mustRun(t, env, newRunner(env, model), g.ID)

	sent := model.Calls[0]
	if !strings.Contains(sent.Prompt, "feria de emprendimiento") || !strings.Contains(sent.Prompt, fx.CompetencyC1.String()) {
		t.Errorf("the prompt carries the idea and the chosen competency:\n%s", sent.Prompt)
	}
	if sent.Tool.Name != "proponer_experiencia" {
		t.Errorf("tool = %q", sent.Tool.Name)
	}

	got := getGeneration(t, h, quispe.token, g.ID)
	if got.Status != "completed" {
		t.Fatalf("status = %q (error %v), want completed", got.Status, got.Error)
	}
	var res struct{ Proposal planning.Proposal }
	if err := json.Unmarshal(got.Result, &res); err != nil {
		t.Fatalf("result: %v (%s)", err, got.Result)
	}
	p := res.Proposal
	if p.Title != "Feria de emprendimiento" || len(p.CompetencyIDs) != 1 || p.CompetencyIDs[0] != fx.CompetencyC1 {
		t.Errorf("proposal = %+v, want the title and the teacher's competency", p)
	}
	if p.StartsOn != "2026-06-13" || p.EndsOn != "2026-06-24" {
		t.Errorf("dates = %s..%s, want 2026-06-13..2026-06-24 (moved past the existing experience)", p.StartsOn, p.EndsOn)
	}

	// The proposal is not an experience until the teacher saves it, and it
	// can be saved as is.
	if plan := getPlan(t, h, quispe.token, classID, fx.TermII); len(plan.Experiences) != 1 {
		t.Fatalf("a proposal must not create an experience; experiences = %d", len(plan.Experiences))
	}
	saved := fmt.Sprintf(`{"term_id":%q,"title":%q,"idea_text":"una feria","situation_text":%q,"starts_on":%q,"ends_on":%q,"competency_ids":[%q]}`,
		fx.TermII, p.Title, p.SituationText, p.StartsOn, p.EndsOn, p.CompetencyIDs[0])
	mustDo(t, h, quispe.token, "POST", "/api/v1/classes/"+classID.String()+"/experiences", saved, http.StatusCreated)

	var tokens int
	var cost float64
	if err := env.Admin.Pool.QueryRow(context.Background(),
		`select input_tokens + output_tokens, cost_usd from agent_generations where id = $1`, g.ID).Scan(&tokens, &cost); err != nil {
		t.Fatal(err)
	}
	if tokens != 1500 || cost <= 0 {
		t.Errorf("usage recorded: tokens = %d, cost = %v", tokens, cost)
	}
}

func TestGenerateCriteriaFillsOnlyGaps(t *testing.T) {
	env := dbtest.Setup(t)
	h := newAPI(t, env, withAgent)
	quispe, _, _ := callers(t, env)
	classID := planClass(t, env)
	fx := env.Fx
	exp := createExperience(t, h, quispe.token, env, classID, "2026-05-18", "2026-05-29", fx.CompetencyC1)
	createCriterion(t, h, quispe.token, exp.ID, fx.CompetencyC1, planPerfC1a, planCapC1a)

	path := "/api/v1/experiences/" + exp.ID.String() + "/criteria/generate"
	body := fmt.Sprintf(`{"competency_id":%q}`, fx.CompetencyC1)
	g := requestGeneration(t, h, quispe.token, path, body)

	model := &llm.Fake{Replies: []llm.FakeReply{reply(map[string]any{"criteria": []map[string]any{
		{"description": "Expresa con números enteros las ganancias y pérdidas de la feria.", "capability_ids": []string{planCapC1b.String()}},
		{"description": "Traduce las ventas a expresiones numéricas.", "capability_ids": []string{planCapC1a.String()}},
		{"description": "Explica con sus palabras qué significa cada número de la feria.", "capability_ids": []string{planCapC1b.String()}},
	}})}}
	runner := newRunner(env, model)
	mustRun(t, env, runner, g.ID)

	if !strings.Contains(model.Calls[0].Prompt, "SIN CRITERIO") {
		t.Errorf("the prompt marks the gap:\n%s", model.Calls[0].Prompt)
	}
	got := getGeneration(t, h, quispe.token, g.ID)
	var res struct {
		CriteriaIDs []uuid.UUID `json:"criteria_ids"`
	}
	if err := json.Unmarshal(got.Result, &res); err != nil || len(res.CriteriaIDs) != 1 {
		t.Fatalf("result = %s (%v), want one criterion: the one filling the gap", got.Result, err)
	}
	e := getExperience(t, h, quispe.token, exp.ID)
	var proposed *repo.ExperienceCriterion
	for i := range e.Criteria {
		if e.Criteria[i].ID == res.CriteriaIDs[0] {
			proposed = &e.Criteria[i]
		}
	}
	if proposed == nil || proposed.ProposedBy != "mawta" || proposed.AcceptedAt != nil ||
		len(proposed.CapabilityIDs) != 1 || proposed.CapabilityIDs[0] != planCapC1b {
		t.Fatalf("proposed criterion = %+v, want pending, by mawta, on the uncovered capability", proposed)
	}

	// Every capability has a criterion now: nothing to generate, no call.
	g2 := requestGeneration(t, h, quispe.token, path, body)
	mustRun(t, env, runner, g2.ID)
	if model.CallCount() != 1 {
		t.Errorf("without gaps the model is not called; calls = %d", model.CallCount())
	}
	if got := getGeneration(t, h, quispe.token, g2.ID); got.Status != "completed" || !strings.Contains(string(got.Result), `"criteria_ids":[]`) {
		t.Errorf("no-gap generation = %+v", got)
	}

	wantError(t, do(t, h, quispe.token, "POST", path, fmt.Sprintf(`{"competency_id":%q}`, fx.CompetencyC2)),
		http.StatusUnprocessableEntity, "competency_not_in_experience")
}

func TestGenerateEvidencesAndSessions(t *testing.T) {
	env := dbtest.Setup(t)
	h := newAPI(t, env, withAgent)
	quispe, _, _ := callers(t, env)
	classID := planClass(t, env)
	fx := env.Fx
	exp := createExperience(t, h, quispe.token, env, classID, "2026-05-18", "2026-05-29", fx.CompetencyC1)
	c1 := createCriterion(t, h, quispe.token, exp.ID, fx.CompetencyC1, planPerfC1a, planCapC1a)
	c2 := createCriterion(t, h, quispe.token, exp.ID, fx.CompetencyC1, planPerfC1b, planCapC1b)

	g := requestGeneration(t, h, quispe.token, "/api/v1/experiences/"+exp.ID.String()+"/evidences/generate", "")
	model := &llm.Fake{Replies: []llm.FakeReply{reply(map[string]any{"evidences": []map[string]any{
		{"name": "Lista de precios de la feria", "kind": "produccion", "criterion_ids": []string{c1.ID.String(), c2.ID.String()}},
		{"name": "Examen sorpresa", "kind": "prueba_escrita", "criterion_ids": []string{c1.ID.String()}},
	}})}}
	runner := newRunner(env, model)
	mustRun(t, env, runner, g.ID)
	e := getExperience(t, h, quispe.token, exp.ID)
	if len(e.Evidences) != 1 || e.Evidences[0].ProposedBy != "mawta" || e.Evidences[0].AcceptedAt != nil ||
		len(e.Evidences[0].CriterionIDs) != 2 {
		t.Fatalf("evidences = %+v, want one pending evidence over both criteria (the invalid kind is dropped)", e.Evidences)
	}
	evidenceID := e.Evidences[0].ID

	// The teacher already planned 2026-05-18: the agent must not touch it.
	mustDo(t, h, quispe.token, "PUT", "/api/v1/experiences/"+exp.ID.String()+"/sessions/2026-05-18",
		`{"title":"Presentamos la feria"}`, http.StatusOK)

	g = requestGeneration(t, h, quispe.token, "/api/v1/experiences/"+exp.ID.String()+"/sessions/generate", "")
	model.Replies = []llm.FakeReply{reply(map[string]any{"sessions": []map[string]any{
		{"date": "2026-05-18", "title": "Otra cosa", "topics": "nada"},
		{"date": "2026-05-20", "title": "¿Cuánto cuesta?", "topics": "Precios y números enteros"},
		{"date": "2026-05-22", "title": "Día cancelado", "topics": "no hay clase"},
		{"date": "2026-05-25", "title": "Armamos la lista de precios", "topics": "Representaciones numéricas", "planned_evidence_id": evidenceID.String()},
		{"date": "2026-05-27", "title": "Feria y reflexión", "topics": "Ganancias y pérdidas"},
	}})}
	mustRun(t, env, runner, g.ID)

	if p := model.Calls[1].Prompt; !strings.Contains(p, "2026-05-20 (miércoles)") || strings.Contains(p, "2026-05-22") {
		t.Errorf("the prompt lists only empty class dates:\n%s", p)
	}
	got := getGeneration(t, h, quispe.token, g.ID)
	if !strings.Contains(string(got.Result), `"session_dates":["2026-05-20","2026-05-25","2026-05-27"]`) {
		t.Errorf("result = %s, want the three empty class dates", got.Result)
	}
	e = getExperience(t, h, quispe.token, exp.ID)
	for _, s := range e.Sessions {
		switch s.Date {
		case "2026-05-18":
			if s.Title != "Presentamos la feria" || s.ProposedBy != "teacher" {
				t.Errorf("the teacher's session was changed: %+v", s)
			}
		default:
			if s.ProposedBy != "mawta" || s.AcceptedAt != nil {
				t.Errorf("proposed session %s = %+v, want pending by mawta", s.Date, s)
			}
		}
	}
	assertPlacement(t, env, evidenceID, "2026-05-25")
}

// failingModel answers with a scripted function, for failures a Fake cannot
// express (like something changing while the model thinks).
type failingModel func(ctx context.Context, req llm.Request) (llm.Response, error)

func (f failingModel) Name() string { return "test-model" }
func (f failingModel) Generate(ctx context.Context, req llm.Request) (llm.Response, error) {
	return f(ctx, req)
}

func TestGenerationFailures(t *testing.T) {
	env := dbtest.Setup(t)
	h := newAPI(t, env, withAgent)
	quispe, _, _ := callers(t, env)
	classID := planClass(t, env)
	fx := env.Fx
	exp := createExperience(t, h, quispe.token, env, classID, "2026-05-18", "2026-05-29", fx.CompetencyC1)
	criteriaPath := "/api/v1/experiences/" + exp.ID.String() + "/criteria/generate"
	criteriaBody := fmt.Sprintf(`{"competency_id":%q}`, fx.CompetencyC1)
	bad := reply(map[string]any{"criteria": []map[string]any{
		{"description": "Inventado", "capability_ids": []string{uuid.NewString()}},
	}})

	t.Run("an invalid answer gets one repair, then fails", func(t *testing.T) {
		g := requestGeneration(t, h, quispe.token, criteriaPath, criteriaBody)
		model := &llm.Fake{Replies: []llm.FakeReply{bad, bad}}
		outcome, err := runJob(t, env, newRunner(env, model), g.ID, 1, 3)
		if err != nil || outcome != agent.OutcomeFailed {
			t.Fatalf("outcome %q err %v, want failed", outcome, err)
		}
		if model.CallCount() != 2 || !strings.Contains(model.Calls[1].Prompt, "no se pudo usar") {
			t.Errorf("want one repair call that explains the problem; calls = %d", model.CallCount())
		}
		got := getGeneration(t, h, quispe.token, g.ID)
		if got.Status != "failed" || got.Error == nil || *got.Error != agent.MsgInvalidAnswer {
			t.Errorf("generation = %+v, want failed with the invalid-answer message", got)
		}
		if e := getExperience(t, h, quispe.token, exp.ID); len(e.Criteria) != 0 {
			t.Errorf("nothing is stored from an invalid answer; criteria = %d", len(e.Criteria))
		}
	})

	t.Run("a transient failure is retried, and fails on the last attempt", func(t *testing.T) {
		g := requestGeneration(t, h, quispe.token, criteriaPath, criteriaBody)
		model := &llm.Fake{Replies: []llm.FakeReply{{Err: errors.New("overloaded")}, {Err: errors.New("overloaded")}}}
		r := newRunner(env, model)
		if _, err := runJob(t, env, r, g.ID, 1, 3); err == nil {
			t.Fatal("a transient failure before the last attempt is returned so the queue retries")
		}
		if got := getGeneration(t, h, quispe.token, g.ID); got.Status != "running" {
			t.Errorf("status = %q, want running between attempts", got.Status)
		}
		outcome, err := runJob(t, env, r, g.ID, 3, 3)
		if err != nil || outcome != agent.OutcomeFailed {
			t.Fatalf("last attempt: outcome %q err %v, want failed", outcome, err)
		}
		if got := getGeneration(t, h, quispe.token, g.ID); got.Error == nil || *got.Error != agent.MsgRetryLater {
			t.Errorf("generation = %+v, want the retry-later message", got)
		}
	})

	t.Run("a permanent failure is not retried", func(t *testing.T) {
		g := requestGeneration(t, h, quispe.token, criteriaPath, criteriaBody)
		model := &llm.Fake{Replies: []llm.FakeReply{{Err: fmt.Errorf("%w: provider status 400", llm.ErrPermanent)}}}
		outcome, err := runJob(t, env, newRunner(env, model), g.ID, 1, 3)
		if err != nil || outcome != agent.OutcomeFailed {
			t.Fatalf("outcome %q err %v, want failed", outcome, err)
		}
	})

	t.Run("a generation past its deadline reads as failed and never runs", func(t *testing.T) {
		g := requestGeneration(t, h, quispe.token, criteriaPath, criteriaBody)
		if _, err := env.Admin.Pool.Exec(context.Background(),
			`update agent_generations set deadline_at = now() - interval '1 minute' where id = $1`, g.ID); err != nil {
			t.Fatal(err)
		}
		if got := getGeneration(t, h, quispe.token, g.ID); got.Status != "failed" || got.Error == nil || *got.Error != repo.ExpiredGenerationMessage {
			t.Errorf("expired generation = %+v, want failed", got)
		}
		model := &llm.Fake{}
		outcome, err := runJob(t, env, newRunner(env, model), g.ID, 1, 3)
		if err != nil || outcome != agent.OutcomeSkipped || model.CallCount() != 0 {
			t.Errorf("outcome %q err %v calls %d, want skipped without a call", outcome, err, model.CallCount())
		}
	})

	t.Run("the experience is deleted while the model thinks", func(t *testing.T) {
		other := createExperience(t, h, quispe.token, env, classID, "2026-06-01", "2026-06-12", fx.CompetencyC1)
		g := requestGeneration(t, h, quispe.token, "/api/v1/experiences/"+other.ID.String()+"/evidences/generate", "")
		createCriterion(t, h, quispe.token, other.ID, fx.CompetencyC1, planPerfC1a, planCapC1a)
		model := failingModel(func(ctx context.Context, req llm.Request) (llm.Response, error) {
			mustDo(t, h, quispe.token, "POST", "/api/v1/experiences/"+other.ID.String()+"/delete", "", http.StatusNoContent)
			return llm.Response{Input: json.RawMessage(`{"evidences":[]}`)}, nil
		})
		outcome, err := runJob(t, env, newRunner(env, model), g.ID, 1, 3)
		if err != nil || outcome != agent.OutcomeFailed {
			t.Fatalf("outcome %q err %v, want failed", outcome, err)
		}
		if got := getGeneration(t, h, quispe.token, g.ID); got.Status != "failed" {
			t.Errorf("generation = %+v, want failed", got)
		}
	})
}

func TestGenerationRoutesRequireAnAssignment(t *testing.T) {
	env := dbtest.Setup(t)
	h := newAPI(t, env, withAgent)
	quispe, rojas, flores := callers(t, env)
	classID := planClass(t, env)
	fx := env.Fx
	exp := createExperience(t, h, quispe.token, env, classID, "2026-05-18", "2026-05-29", fx.CompetencyC1)
	g := requestGeneration(t, h, quispe.token, "/api/v1/experiences/"+exp.ID.String()+"/sessions/generate", "")

	routes := []route{
		{"experience proposal", "POST", "/api/v1/classes/" + classID.String() + "/experience-proposals",
			fmt.Sprintf(`{"term_id":%q,"idea_text":"una feria"}`, fx.TermII)},
		{"criteria", "POST", "/api/v1/experiences/" + exp.ID.String() + "/criteria/generate",
			fmt.Sprintf(`{"competency_id":%q}`, fx.CompetencyC1)},
		{"evidences", "POST", "/api/v1/experiences/" + exp.ID.String() + "/evidences/generate", ""},
		{"sessions", "POST", "/api/v1/experiences/" + exp.ID.String() + "/sessions/generate", ""},
		{"read a generation", "GET", "/api/v1/generations/" + g.ID.String(), ""},
	}
	for _, rt := range routes {
		if w := do(t, h, rojas.token, rt.method, rt.path, rt.body); w.Code != http.StatusForbidden || errorCode(t, w) != "not_assigned_to_class" {
			t.Errorf("%s as %s: got %d, want 403 not_assigned_to_class", rt.name, rojas.name, w.Code)
		}
		if w := do(t, h, flores.token, rt.method, rt.path, rt.body); w.Code != http.StatusNotFound && w.Code != http.StatusForbidden {
			t.Errorf("%s as %s: got %d, want 404 or 403", rt.name, flores.name, w.Code)
		}
	}
}
