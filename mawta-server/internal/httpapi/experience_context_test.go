package httpapi_test

import (
	"fmt"
	"net/http"
	"strings"
	"testing"

	"mawta-server/internal/agent/llm"
	"mawta-server/internal/dbtest"
)

// The teacher's event/context is the only source of an event the planning agent
// may use. These tests check what the model is told, on every request.

func proposeWithContext(t *testing.T, env *dbtest.Env, contextField string) *llm.Fake {
	t.Helper()
	h := newAPI(t, env, withAgent)
	quispe, _, _ := callers(t, env)
	classID := planClass(t, env)

	path := "/api/v1/classes/" + classID.String() + "/experience-proposals"
	body := fmt.Sprintf(`{"term_id":%q,"idea_text":"Practicar vueltos en la tiendita","competency_ids":[%q]%s}`,
		env.Fx.TermII, env.Fx.CompetencyC1, contextField)
	g := requestGeneration(t, h, quispe.token, path, body)

	model := &llm.Fake{Replies: []llm.FakeReply{reply(map[string]any{
		"title":          "Tiendita escolar",
		"situation_text": "La tiendita del aula necesita vueltos correctos. ¿Cómo damos el cambio sin errores?",
		"competency_ids": []string{env.Fx.CompetencyC1.String()},
		"starts_on":      "2026-06-01",
		"ends_on":        "2026-06-12",
	})}}
	mustRun(t, env, newRunner(env, model), g.ID)
	return model
}

func TestExperienceProposalSaysWhenThereIsNoEvent(t *testing.T) {
	env := dbtest.Setup(t)
	model := proposeWithContext(t, env, "")

	if len(model.Calls) == 0 {
		t.Fatal("the model was not called")
	}
	prompt := model.Calls[0].Prompt
	if !strings.Contains(prompt, "Contexto del docente: ninguno") {
		t.Errorf("an empty context must say so explicitly:\n%s", prompt)
	}
	if strings.Contains(prompt, "<contexto_del_docente>") {
		t.Errorf("no context tag without teacher text:\n%s", prompt)
	}
}

func TestExperienceProposalPassesTheTeacherContext(t *testing.T) {
	env := dbtest.Setup(t)
	model := proposeWithContext(t, env, `,"context_text":"Feria del aula de compras"`)

	if len(model.Calls) == 0 {
		t.Fatal("the model was not called")
	}
	prompt := model.Calls[0].Prompt
	if !strings.Contains(prompt, "<contexto_del_docente>\nFeria del aula de compras\n</contexto_del_docente>") {
		t.Errorf("the teacher's context is sent inside its tag:\n%s", prompt)
	}
	if strings.Contains(prompt, "ninguno") {
		t.Errorf("a context given must not also say none:\n%s", prompt)
	}
}

func TestExperienceContextIsCapped(t *testing.T) {
	env := dbtest.Setup(t)
	h := newAPI(t, env, withAgent)
	quispe, _, _ := callers(t, env)
	classID := planClass(t, env)

	path := "/api/v1/classes/" + classID.String() + "/experience-proposals"
	long := strings.Repeat("a", 301)
	body := fmt.Sprintf(`{"term_id":%q,"idea_text":"Vueltos","context_text":%q}`, env.Fx.TermII, long)
	mustDo(t, h, quispe.token, "POST", path, body, http.StatusBadRequest)
}
